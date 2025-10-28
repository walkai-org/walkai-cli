"""Tests for container image push helpers."""

import base64
import subprocess
from typing import Any

import httpx
import pytest

import walkai.push as push
from walkai.configuration import WalkAIAPIConfig


@pytest.fixture()
def sample_credentials() -> push.RegistryCredentials:
    return push.RegistryCredentials(
        url="123456789012.dkr.ecr.us-west-2.amazonaws.com/team:latest",
        username="hueso",
        password="badpassword",
    )


def test_fetch_registry_credentials_requests_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class DummyResponse:
        status_code = 200
        text = ""

        def json(self) -> dict[str, str]:
            return {
                "token": base64.b64encode(b"alice:secret").decode("utf-8"),
                "ecr_arn": "123456789012.dkr.ecr.us-west-2.amazonaws.com/team:latest",
            }

    def fake_get(
        url: str,
        *,
        headers: dict[str, str],
        timeout: float,
    ) -> DummyResponse:
        captured["url"] = url
        captured["headers"] = headers
        captured["timeout"] = timeout
        return DummyResponse()

    monkeypatch.setattr(push.httpx, "get", fake_get)

    api_config = WalkAIAPIConfig(url="https://api.walkai.ai", pat="pat")
    credentials = push.fetch_registry_credentials(api_config)

    assert credentials == push.RegistryCredentials(
        url="123456789012.dkr.ecr.us-west-2.amazonaws.com/team:latest",
        username="alice",
        password="secret",
    )
    assert captured["url"] == "https://api.walkai.ai/registry"
    assert captured["headers"] == {"Authorization": "Bearer pat"}
    assert captured["timeout"] == 30


def test_fetch_registry_credentials_handles_http_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class DummyResponse:
        status_code = 500
        text = "boom"

        def json(self) -> dict[str, str]:  # pragma: no cover - should not run
            raise AssertionError("json() should not be called")

    monkeypatch.setattr(push.httpx, "get", lambda *args, **kwargs: DummyResponse())

    api_config = WalkAIAPIConfig(url="https://api.walkai.ai", pat="pat")

    with pytest.raises(push.PushError, match="Failed to obtain registry credentials"):
        push.fetch_registry_credentials(api_config)


def test_fetch_registry_credentials_handles_request_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = httpx.Request("GET", "https://api.walkai.ai/registry/credentials/")

    def fake_get(*args: object, **kwargs: object) -> None:
        raise httpx.RequestError("boom", request=request)

    monkeypatch.setattr(push.httpx, "get", fake_get)

    api_config = WalkAIAPIConfig(url="https://api.walkai.ai", pat="pat")

    with pytest.raises(push.PushError, match="Failed to reach WalkAI API"):
        push.fetch_registry_credentials(api_config)


def test_fetch_registry_credentials_rejects_invalid_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class DummyResponse:
        status_code = 200
        text = ""

        def json(self) -> dict[str, str]:
            raise ValueError("bad json")

    monkeypatch.setattr(push.httpx, "get", lambda *args, **kwargs: DummyResponse())

    api_config = WalkAIAPIConfig(url="https://api.walkai.ai", pat="pat")

    with pytest.raises(
        push.PushError, match="WalkAI API returned malformed registry credentials"
    ):
        push.fetch_registry_credentials(api_config)


def test_fetch_registry_credentials_requires_all_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class DummyResponse:
        status_code = 200
        text = ""

        def json(self) -> dict[str, str]:
            return {
                "token": base64.b64encode(b"alice:secret").decode("utf-8"),
            }

    monkeypatch.setattr(push.httpx, "get", lambda *args, **kwargs: DummyResponse())

    api_config = WalkAIAPIConfig(url="https://api.walkai.ai", pat="pat")

    with pytest.raises(push.PushError, match="registry\\.ecr_arn"):
        push.fetch_registry_credentials(api_config)


def test_push_image_runs_expected_commands(
    monkeypatch: pytest.MonkeyPatch, sample_credentials: push.RegistryCredentials
) -> None:
    calls: list[dict[str, Any]] = []

    def fake_run(
        cmd: list[str],
        *,
        check: bool,
        input: str | None = None,  # noqa: A002
        text: bool | None = None,
    ) -> None:
        calls.append({"cmd": cmd, "input": input, "text": text, "check": check})

    monkeypatch.setattr(push.subprocess, "run", fake_run)

    remote = push.push_image("demo:latest", sample_credentials)

    assert remote == "123456789012.dkr.ecr.us-west-2.amazonaws.com/team:demo"
    assert calls[0]["cmd"] == [
        "docker",
        "login",
        "123456789012.dkr.ecr.us-west-2.amazonaws.com/team:latest",
        "--username",
        "hueso",
        "--password-stdin",
    ]
    assert calls[0]["input"] == "badpassword"
    assert calls[0]["text"] is True
    assert calls[1]["cmd"] == ["docker", "tag", "demo:latest", remote]
    assert calls[2]["cmd"] == ["docker", "push", remote]


@pytest.mark.parametrize(
    ("local", "expected"),
    [
        ("demo:latest", "demo"),
        ("registry:5000/namespace/demo:latest", "demo"),
        ("ghcr.io/acme/demo@sha256:abcdef", "demo"),
        ("demo", "demo"),
    ],
)
def test_normalize_local_image_name_handles_common_variants(
    local: str, expected: str
) -> None:
    assert push._normalize_local_image_name(local) == expected


def test_push_image_wraps_called_process_error(
    monkeypatch: pytest.MonkeyPatch, sample_credentials: push.RegistryCredentials
) -> None:
    def failing_run(
        cmd: list[str],
        *,
        check: bool,
        input: str | None = None,  # noqa: A002
        text: bool | None = None,
    ) -> None:
        raise subprocess.CalledProcessError(returncode=42, cmd=cmd)

    monkeypatch.setattr(push.subprocess, "run", failing_run)

    with pytest.raises(push.PushError, match="command failed with exit code 42"):
        push.push_image("demo:latest", sample_credentials)
