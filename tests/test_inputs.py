"""Tests for input volume helpers and CLI commands."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from walkai import configuration
from walkai.configuration import WalkAIAPIConfig, WalkAIConfig
from walkai.inputs import (
    InputError,
    create_input_volume,
    list_input_volumes,
    list_volume_objects,
    request_input_upload_urls,
    upload_files_to_presigned,
)
from walkai.main import app

runner = CliRunner()


@pytest.fixture()
def isolated_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Point the configuration helpers at a temporary file."""

    config_dir = tmp_path / "config"
    config_file = config_dir / "config.toml"
    monkeypatch.setattr(configuration, "_CONFIG_DIR", config_dir)
    monkeypatch.setattr(configuration, "_CONFIG_FILE", config_file)
    return config_file


def _save_config() -> None:
    configuration.save_config(
        WalkAIConfig(
            walkai_api=WalkAIAPIConfig(
                url="https://api.walkai.ai",
                pat="pat-token",
            ),
        )
    )


def test_list_input_volumes_requests_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class DummyResponse:
        status_code = 200
        text = ""

        def json(self) -> list[dict[str, object]]:
            return [
                {
                    "id": 141,
                    "pvc_name": "input-cb263c5f",
                    "size": 1,
                    "is_input": True,
                },
                {
                    "id": 139,
                    "pvc_name": "input-6f0668b6",
                    "size": 1,
                    "is_input": True,
                },
            ]

    def fake_get(
        url: str,
        *,
        headers: dict[str, str],
        params: dict[str, object],
        timeout: float,
    ) -> DummyResponse:
        captured["url"] = url
        captured["headers"] = headers
        captured["params"] = params
        captured["timeout"] = timeout
        return DummyResponse()

    monkeypatch.setattr("walkai.inputs.httpx.get", fake_get)

    api_config = WalkAIAPIConfig(url="https://api.walkai.ai", pat="pat")
    volumes = list_input_volumes(api_config)

    assert volumes == [
        {"id": 141, "name": "input-cb263c5f", "size": 1},
        {"id": 139, "name": "input-6f0668b6", "size": 1},
    ]
    assert captured["url"] == "https://api.walkai.ai/volumes/"
    assert captured["headers"] == {"Authorization": "Bearer pat"}
    assert captured["params"] == {"is_input": True}
    assert captured["timeout"] == 30.0


def test_list_volume_objects_returns_objects(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class DummyResponse:
        status_code = 200
        text = ""

        def json(self) -> dict[str, object]:
            return {
                "prefix": "users/1/inputs/input-cb263c5f",
                "objects": [
                    {
                        "key": "file-a.txt",
                        "size": 10,
                        "last_modified": "2024-01-01T00:00:00Z",
                        "etag": "etag-1",
                    }
                ],
                "truncated": False,
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

    monkeypatch.setattr("walkai.inputs.httpx.get", fake_get)

    api_config = WalkAIAPIConfig(url="https://api.walkai.ai", pat="pat")
    objects = list_volume_objects(api_config, volume_id=141)

    assert objects == [
        {
            "key": "file-a.txt",
            "size": 10,
            "last_modified": "2024-01-01T00:00:00Z",
            "etag": "etag-1",
        }
    ]
    assert captured["url"] == "https://api.walkai.ai/volumes/141/objects"
    assert captured["headers"] == {"Authorization": "Bearer pat"}
    assert captured["timeout"] == 30.0


def test_list_volume_objects_handles_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    class DummyResponse:
        status_code = 404
        text = "not found"

        def json(self) -> dict[str, object]:  # pragma: no cover - should not run
            raise AssertionError("json() should not be called")

    monkeypatch.setattr(
        "walkai.inputs.httpx.get", lambda *args, **kwargs: DummyResponse()
    )

    api_config = WalkAIAPIConfig(url="https://api.walkai.ai", pat="pat")

    with pytest.raises(InputError, match="Volume '99' was not found."):
        list_volume_objects(api_config, volume_id=99)


def test_create_input_volume_posts_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class DummyResponse:
        status_code = 201
        text = ""

        def json(self) -> dict[str, object]:
            return {
                "volume": {
                    "id": 1,
                    "pvc_name": "input-abc",
                    "size": 5,
                    "key_prefix": "users/1/inputs/input-abc",
                    "is_input": True,
                }
            }

    def fake_post(
        url: str,
        *,
        json: dict[str, object],  # noqa: A002 - matches httpx signature
        headers: dict[str, str],
        timeout: float,
    ) -> DummyResponse:
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        captured["timeout"] = timeout
        return DummyResponse()

    monkeypatch.setattr("walkai.inputs.httpx.post", fake_post)

    api_config = WalkAIAPIConfig(url="https://api.walkai.ai", pat="pat")
    volume = create_input_volume(api_config, size=5)

    assert volume["id"] == 1
    assert volume["name"] == "input-abc"
    assert volume["size"] == 5
    assert captured["url"] == "https://api.walkai.ai/volumes/inputs"
    assert captured["json"] == {"storage": 5}
    assert captured["headers"] == {"Authorization": "Bearer pat"}
    assert captured["timeout"] == 30.0


def test_request_input_upload_urls_posts_names(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class DummyResponse:
        status_code = 200
        text = ""

        def json(self) -> dict[str, object]:
            return {"presigneds": ["url-a", "url-b"]}

    def fake_post(
        url: str,
        *,
        json: dict[str, object],  # noqa: A002 - matches httpx signature
        headers: dict[str, str],
        timeout: float,
    ) -> DummyResponse:
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        captured["timeout"] = timeout
        return DummyResponse()

    monkeypatch.setattr("walkai.inputs.httpx.post", fake_post)

    api_config = WalkAIAPIConfig(url="https://api.walkai.ai", pat="pat")
    urls = request_input_upload_urls(
        api_config, volume_id=1, filenames=["a.txt", "b.txt"]
    )

    assert urls == ["url-a", "url-b"]
    assert captured["url"] == "https://api.walkai.ai/volumes/inputs/presigneds"
    assert captured["json"] == {"volume_id": 1, "file_names": ["a.txt", "b.txt"]}
    assert captured["headers"] == {"Authorization": "Bearer pat"}
    assert captured["timeout"] == 30.0


def test_upload_files_to_presigned_puts_content(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    uploaded: list[dict[str, object]] = []

    def fake_put(
        url: str,
        *,
        content,
        headers: dict[str, str],
        timeout: float,
    ):
        uploaded.append(
            {"url": url, "data": content.read(), "headers": headers, "timeout": timeout}
        )

        class DummyResponse:
            status_code = 200
            text = ""

        return DummyResponse()

    monkeypatch.setattr("walkai.inputs.httpx.put", fake_put)

    file_a = tmp_path / "a.txt"
    file_b = tmp_path / "b.txt"
    file_a.write_text("hello")
    file_b.write_text("world")

    upload_files_to_presigned(["url-a", "url-b"], [file_a, file_b])

    assert uploaded == [
        {
            "url": "url-a",
            "data": b"hello",
            "headers": {"Content-Type": "application/octet-stream"},
            "timeout": 60.0,
        },
        {
            "url": "url-b",
            "data": b"world",
            "headers": {"Content-Type": "application/octet-stream"},
            "timeout": 60.0,
        },
    ]


def test_upload_files_to_presigned_validates_lengths(tmp_path: Path) -> None:
    file_a = tmp_path / "a.txt"
    file_a.write_text("hello")

    with pytest.raises(InputError, match="number of presigned URLs"):
        upload_files_to_presigned(["only-one"], [file_a, file_a])


def test_cli_inputs_list_outputs_volumes(
    monkeypatch: pytest.MonkeyPatch, isolated_config: Path
) -> None:
    _save_config()
    monkeypatch.setattr(
        "walkai.main.list_input_volumes",
        lambda api, *, timeout=30.0: [
            {"id": 141, "name": "input-cb263c5f", "size": 1},
            {"id": 139, "name": "input-6f0668b6", "size": 2},
        ],
    )

    result = runner.invoke(app, ["input", "list"])

    assert result.exit_code == 0, result.stderr
    assert "Input volumes:" in result.stdout
    assert "- 141: input-cb263c5f (size: 1)" in result.stdout
    assert "- 139: input-6f0668b6 (size: 2)" in result.stdout


def test_cli_inputs_get_displays_objects(
    monkeypatch: pytest.MonkeyPatch, isolated_config: Path
) -> None:
    _save_config()

    def fake_list(
        api: WalkAIAPIConfig, *, volume_id: int, timeout: float = 30.0
    ) -> list[dict[str, object]]:
        assert volume_id == 141
        return [{"key": "file-a.txt", "size": 10}]

    monkeypatch.setattr("walkai.main.list_volume_objects", fake_list)

    result = runner.invoke(app, ["input", "get", "141"])

    assert result.exit_code == 0, result.stderr
    assert "Objects in volume 141:" in result.stdout
    assert "- file-a.txt (10 bytes)" in result.stdout


def test_cli_inputs_create_wires_calls(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, isolated_config: Path
) -> None:
    _save_config()

    created: dict[str, object] = {}
    upload_requested: dict[str, object] = {}
    uploads: dict[str, list[str]] = {"urls": [], "files": []}

    monkeypatch.setattr(
        "walkai.main.create_input_volume",
        lambda api, *, size: created.update({"size": size})
        or {"id": 5, "name": "input-5"},
    )
    monkeypatch.setattr(
        "walkai.main.request_input_upload_urls",
        lambda api, *, volume_id, filenames: upload_requested.update(
            {"volume_id": volume_id, "filenames": filenames}
        )
        or ["url-a", "url-b"],
    )
    monkeypatch.setattr(
        "walkai.main.upload_files_to_presigned",
        lambda urls, files: uploads["urls"].extend(urls)
        or uploads["files"].extend([str(f) for f in files]),
    )

    file_a = tmp_path / "a.txt"
    file_b = tmp_path / "b.txt"
    file_a.write_text("hello")
    file_b.write_text("world")

    result = runner.invoke(
        app,
        [
            "input",
            "create",
            "--size",
            "3",
            "--file",
            str(file_a),
            "--file",
            str(file_b),
        ],
    )

    assert result.exit_code == 0, result.stderr
    assert created["size"] == 3
    assert upload_requested == {"volume_id": 5, "filenames": ["a.txt", "b.txt"]}
    assert uploads["urls"] == ["url-a", "url-b"]
    assert uploads["files"] == [str(file_a), str(file_b)]
    assert "Created input volume 5 and uploaded 2 file(s)." in result.stdout


def test_cli_inputs_create_requires_files(
    monkeypatch: pytest.MonkeyPatch, isolated_config: Path
) -> None:
    _save_config()

    result = runner.invoke(app, ["input", "create", "--size", "3"])

    assert result.exit_code == 1
    assert "At least one --file must be provided." in (result.stderr or result.stdout)
