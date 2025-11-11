"""Tests for the submit command."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from walkai import configuration
from walkai.configuration import WalkAIAPIConfig, WalkAIConfig
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


def _create_project(tmp_path: Path, *, gpu: str = "1g.10gb", storage: int = 2) -> Path:
    project_dir = tmp_path / "demo"
    project_dir.mkdir()

    project_lines = [
        "[project]",
        'name = "demo"',
        "[tool.walkai]",
        'entrypoint = "python main.py"',
        "os_dependencies = []",
        f'gpu = "{gpu}"',
        f"storage = {storage}",
    ]
    (project_dir / "pyproject.toml").write_text("\n".join(project_lines) + "\n")
    (project_dir / "main.py").write_text("print('walkai submit')\n")

    return project_dir


def test_submit_invokes_walkai_api(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, isolated_config: Path
) -> None:
    project_dir = _create_project(tmp_path, storage=5)

    configuration.save_config(
        WalkAIConfig(
            walkai_api=WalkAIAPIConfig(
                url="https://api.walkai.ai",
                pat="pat-token",
            ),
        )
    )

    captured: dict[str, object] = {}

    class DummyResponse:
        def __init__(self) -> None:
            self.status_code = 201
            self.text = ""

        def json(self) -> dict[str, object]:
            return {"job_id": "job-123", "pod": "pod-name"}

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

    monkeypatch.setattr("walkai.main.httpx.post", fake_post)

    result = runner.invoke(app, ["submit", str(project_dir), "--image", "demo:latest"])

    assert result.exit_code == 0, result.stdout
    assert (
        "Job submitted successfully with ID: job-123 and pod pod-name" in result.stdout
    )
    assert captured["url"] == "https://api.walkai.ai/jobs/"
    assert captured["json"] == {
        "image": "demo:latest",
        "gpu": "1g.10gb",
        "storage": 5,
    }
    assert captured["headers"] == {"Authorization": "Bearer pat-token"}
    assert captured["timeout"] == 30


def test_submit_can_forward_secrets(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, isolated_config: Path
) -> None:
    project_dir = _create_project(tmp_path)

    configuration.save_config(
        WalkAIConfig(
            walkai_api=WalkAIAPIConfig(
                url="https://api.walkai.ai",
                pat="pat-token",
            ),
        )
    )

    captured: dict[str, object] = {}

    class DummyResponse:
        def __init__(self) -> None:
            self.status_code = 201
            self.text = ""

        def json(self) -> dict[str, object]:
            return {"job_id": "job-123", "pod": "pod-name"}

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

    monkeypatch.setattr("walkai.main.httpx.post", fake_post)

    result = runner.invoke(
        app,
        [
            "submit",
            str(project_dir),
            "--secret",
            "db-creds",
            "--secret",
            "api-token",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert captured["json"] == {
        "image": "walkai/demo:latest",
        "gpu": "1g.10gb",
        "storage": 2,
        "secret_names": ["db-creds", "api-token"],
    }


def test_submit_requires_api_credentials(tmp_path: Path, isolated_config: Path) -> None:
    project_dir = _create_project(tmp_path)

    result = runner.invoke(app, ["submit", str(project_dir)])

    assert result.exit_code == 1
    assert "No WalkAI API configuration found" in result.output


def test_submit_requires_gpu_configuration(
    tmp_path: Path, isolated_config: Path
) -> None:
    project_dir = tmp_path / "demo"
    project_dir.mkdir()
    (project_dir / "main.py").write_text("print('walkai submit')\n")
    (project_dir / "pyproject.toml").write_text(
        """[project]
name = "demo"
[tool.walkai]
entrypoint = "python main.py"
os_dependencies = []
storage = 2
"""
    )

    configuration.save_config(
        WalkAIConfig(
            walkai_api=WalkAIAPIConfig(
                url="https://api.walkai.ai",
                pat="pat-token",
            ),
        )
    )

    result = runner.invoke(app, ["submit", str(project_dir)])

    assert result.exit_code == 1
    assert "gpu" in result.output.lower()
