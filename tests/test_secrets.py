"""Tests for secrets helpers and CLI commands."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from walkai import configuration
from walkai.configuration import WalkAIAPIConfig, WalkAIConfig
from walkai.main import app
from walkai.secrets import SecretsError, parse_env_file

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


def test_parse_env_file_parses_values(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        """
        # comment
        export API_KEY=abc123
        USERNAME="walkai"
        EMPTY=
        """
    )

    parsed = parse_env_file(env_file)

    assert parsed == {
        "API_KEY": "abc123",
        "USERNAME": "walkai",
        "EMPTY": "",
    }


def test_parse_env_file_rejects_invalid_line(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("MALFORMED LINE")

    with pytest.raises(SecretsError, match="missing '='"):
        parse_env_file(env_file)


def test_cli_secrets_list_outputs_names(
    monkeypatch: pytest.MonkeyPatch, isolated_config: Path
) -> None:
    _save_config()

    def fake_list(
        api: WalkAIAPIConfig, *, timeout: float = 30.0
    ) -> list[dict[str, str]]:
        return [{"name": "alpha"}, {"name": "beta"}]

    monkeypatch.setattr("walkai.main.list_secrets", fake_list)

    result = runner.invoke(app, ["secrets", "list"])

    assert result.exit_code == 0, result.stderr
    assert "- alpha" in result.stdout
    assert "- beta" in result.stdout


def test_cli_secrets_list_reports_empty(
    monkeypatch: pytest.MonkeyPatch, isolated_config: Path
) -> None:
    _save_config()
    monkeypatch.setattr("walkai.main.list_secrets", lambda api, *, timeout=30.0: [])

    result = runner.invoke(app, ["secrets", "list"])

    assert result.exit_code == 0
    assert "No secrets found." in result.stdout


def test_cli_secrets_get_displays_keys(
    monkeypatch: pytest.MonkeyPatch, isolated_config: Path
) -> None:
    _save_config()

    def fake_get(
        api: WalkAIAPIConfig, *, name: str, timeout: float = 30.0
    ) -> dict[str, object]:
        assert name == "prod"
        return {"name": "prod", "keys": ["foo", "bar"]}

    monkeypatch.setattr("walkai.main.get_secret", fake_get)

    result = runner.invoke(app, ["secrets", "get", "prod"])

    assert result.exit_code == 0, result.stderr
    assert "Secret: prod" in result.stdout
    assert "- foo" in result.stdout
    assert "- bar" in result.stdout


def test_cli_secrets_get_supports_json_output(
    monkeypatch: pytest.MonkeyPatch, isolated_config: Path
) -> None:
    _save_config()
    monkeypatch.setattr(
        "walkai.main.get_secret",
        lambda api, *, name, timeout=30.0: {"name": name, "keys": []},
    )

    result = runner.invoke(app, ["secrets", "get", "prod", "--json"])

    assert result.exit_code == 0, result.stderr
    assert '"name": "prod"' in result.stdout
    assert '"keys": []' in result.stdout


def test_cli_secrets_create_merges_env_file_and_inline_data(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, isolated_config: Path
) -> None:
    _save_config()
    env_file = tmp_path / ".env"
    env_file.write_text("SHARED=from-env\nTOKEN=123\n")

    captured: dict[str, object] = {}

    def fake_create(
        api: WalkAIAPIConfig, *, name: str, data: dict[str, str], timeout: float = 30.0
    ) -> None:
        captured["name"] = name
        captured["data"] = data

    monkeypatch.setattr("walkai.main.create_secret", fake_create)

    result = runner.invoke(
        app,
        [
            "secrets",
            "create",
            "prod",
            "--env-file",
            str(env_file),
            "--data",
            "SHARED=overridden",
            "--data",
            "LOCAL=1",
        ],
    )

    assert result.exit_code == 0, result.stderr
    assert captured["name"] == "prod"
    assert captured["data"] == {
        "SHARED": "overridden",
        "TOKEN": "123",
        "LOCAL": "1",
    }


def test_cli_secrets_create_requires_data(
    isolated_config: Path,
) -> None:
    _save_config()

    result = runner.invoke(app, ["secrets", "create", "empty"])

    assert result.exit_code == 1
    assert "Secret data is empty" in (result.stderr or result.stdout)


def test_cli_secrets_create_validates_pairs(
    isolated_config: Path,
) -> None:
    _save_config()

    result = runner.invoke(app, ["secrets", "create", "prod", "--data", "invalid"])

    assert result.exit_code == 1
    assert "Invalid --data value" in (result.stderr or result.stdout)


def test_cli_secrets_delete_confirms_before_calling_api(
    monkeypatch: pytest.MonkeyPatch, isolated_config: Path
) -> None:
    _save_config()
    called: dict[str, str] = {}

    def fake_delete(api: WalkAIAPIConfig, *, name: str, timeout: float = 30.0) -> None:
        called["name"] = name

    monkeypatch.setattr("walkai.main.delete_secret", fake_delete)

    result = runner.invoke(app, ["secrets", "delete", "prod"], input="y\n")

    assert result.exit_code == 0, result.stderr
    assert called["name"] == "prod"
    assert "Secret 'prod' deleted." in result.stdout


def test_cli_secrets_delete_can_abort(
    monkeypatch: pytest.MonkeyPatch, isolated_config: Path
) -> None:
    _save_config()

    def fake_delete(api: WalkAIAPIConfig, *, name: str, timeout: float = 30.0) -> None:
        raise AssertionError("delete_secret should not be called when aborted")

    monkeypatch.setattr("walkai.main.delete_secret", fake_delete)

    result = runner.invoke(app, ["secrets", "delete", "prod"], input="n\n")

    assert result.exit_code == 0
    assert "Aborted." in result.stdout
