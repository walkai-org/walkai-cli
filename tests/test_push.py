"""Tests for container image push helpers."""

import subprocess
from typing import Any

import pytest

import walkai.push as push
from walkai.configuration import RegistryConfig


@pytest.fixture()
def sample_config() -> RegistryConfig:
    return RegistryConfig(
        url="https://registry.example.com/team",
        username="hueso",
        password="badpassword",
    )


def test_push_image_runs_expected_commands(
    monkeypatch: pytest.MonkeyPatch, sample_config: RegistryConfig
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

    remote = push.push_image("demo:latest", sample_config)

    assert remote == "registry.example.com/team/demo:latest"
    assert calls[0]["cmd"] == [
        "docker",
        "login",
        "registry.example.com",
        "--username",
        "hueso",
        "--password-stdin",
    ]
    assert calls[0]["input"] == "badpassword"
    assert calls[0]["text"] is True
    assert calls[1]["cmd"] == ["docker", "tag", "demo:latest", remote]
    assert calls[2]["cmd"] == ["docker", "push", remote]


def test_push_image_honours_repository_override(
    monkeypatch: pytest.MonkeyPatch, sample_config: RegistryConfig
) -> None:
    recorded: list[list[str]] = []

    def fake_run(
        cmd: list[str],
        *,
        check: bool,
        input: str | None = None,  # noqa: A002
        text: bool | None = None,
    ) -> None:
        recorded.append(cmd)

    monkeypatch.setattr(push.subprocess, "run", fake_run)

    remote = push.push_image(
        "demo:latest",
        sample_config,
        repository="custom/repo",
        client="podman",
    )

    assert remote == "registry.example.com/team/custom/repo"
    assert recorded[0][0] == "podman"
    assert recorded[-1] == ["podman", "push", remote]


def test_push_image_rejects_empty_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        push.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("should not run commands")
        ),
    )

    config = RegistryConfig(url="   ", username="alice", password="secret")

    with pytest.raises(push.PushError, match="Registry URL may not be empty"):
        push.push_image("demo:latest", config)


def test_push_image_requires_host_in_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        push.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("should not run commands")
        ),
    )

    config = RegistryConfig(
        url="https:///namespace", username="alice", password="secret"
    )

    with pytest.raises(push.PushError, match="Registry host is missing"):
        push.push_image("demo:latest", config)


def test_push_image_wraps_called_process_error(
    monkeypatch: pytest.MonkeyPatch, sample_config: RegistryConfig
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
        push.push_image("demo:latest", sample_config)
