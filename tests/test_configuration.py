"""Tests for configuration helpers and CLI integration."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from walkai import configuration
from walkai.configuration import RegistryConfig, WalkAIAPIConfig, WalkAIConfig
from walkai.main import app

runner = CliRunner()


@pytest.fixture()
def isolated_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Point the configuration module at a temporary config location."""

    config_dir = tmp_path / "config"
    config_file = config_dir / "config.toml"
    monkeypatch.setattr(configuration, "_CONFIG_DIR", config_dir)
    monkeypatch.setattr(configuration, "_CONFIG_FILE", config_file)
    return config_file


def test_delete_config_returns_false_when_missing(isolated_config: Path) -> None:
    assert configuration.delete_config() is False
    assert not isolated_config.exists()


def test_delete_config_removes_existing_file(isolated_config: Path) -> None:
    isolated_config.parent.mkdir(parents=True)
    isolated_config.write_text("[registry]\n")

    assert configuration.delete_config() is True
    assert not isolated_config.exists()


def test_save_and_load_round_trip(isolated_config: Path) -> None:
    config = WalkAIConfig(
        registry=RegistryConfig(
            url="registry.example.com/team",
            username="alice",
            password="hunter2",
        ),
        walkai_api=WalkAIAPIConfig(
            url="https://api.walkai.ai/v1",
            pat="walkai_pat_token",
        ),
    )

    saved_path = configuration.save_config(config)

    assert saved_path == isolated_config
    assert 'url = "registry.example.com/team"' in isolated_config.read_text()
    loaded = configuration.load_config()
    assert loaded is not None
    assert loaded.registry == config.registry
    assert loaded.walkai_api == config.walkai_api


def test_load_config_returns_none_when_missing(isolated_config: Path) -> None:
    assert configuration.load_config() is None


def test_load_config_raises_for_invalid_payload(isolated_config: Path) -> None:
    isolated_config.parent.mkdir(parents=True)
    isolated_config.write_text("invalid = true\n")

    with pytest.raises(
        configuration.ConfigError, match=r"missing the \[registry\] section"
    ):
        configuration.load_config()


def test_load_config_handles_missing_walkai_section(isolated_config: Path) -> None:
    isolated_config.parent.mkdir(parents=True)
    isolated_config.write_text(
        """[registry]
url = "registry.example.com"
username = "bob"
password = "pw"
"""
    )

    loaded = configuration.load_config()

    assert loaded is not None
    assert loaded.walkai_api is None


def test_load_config_raises_for_incomplete_walkai_section(
    isolated_config: Path,
) -> None:
    isolated_config.parent.mkdir(parents=True)
    isolated_config.write_text(
        """[registry]
url = "registry.example.com"
username = "bob"
password = "pw"

[walkai]
api_url = "https://api.walkai.ai"
"""
    )

    with pytest.raises(configuration.ConfigError, match=r"walkai\.pat"):
        configuration.load_config()


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("https://registry.example.com/team", "registry.example.com/team"),
        ("http://registry.example.com/", "registry.example.com"),
        ("registry.example.com//team/", "registry.example.com//team"),
        ("   registry.example.com   ", "registry.example.com"),
    ],
)
def test_normalise_registry_host_behaviour(raw: str, expected: str) -> None:
    assert configuration.normalise_registry_host(raw) == expected


def test_cli_config_saves_credentials(isolated_config: Path) -> None:
    result = runner.invoke(
        app,
        [
            "config",
            "--url",
            "registry.example.com/team",
            "--username",
            "alice",
            "--password",
            "hunter2",
            "--api-url",
            "https://api.walkai.ai",
            "--pat",
            "pat-token",
            "--show-path",
        ],
    )

    assert result.exit_code == 0
    assert "Registry configuration saved." in result.stdout
    assert f"Location: {isolated_config}" in result.stdout
    loaded = configuration.load_config()
    assert loaded is not None
    assert loaded.registry == RegistryConfig(
        url="registry.example.com/team",
        username="alice",
        password="hunter2",
    )
    assert loaded.walkai_api == WalkAIAPIConfig(
        url="https://api.walkai.ai",
        pat="pat-token",
    )


def test_cli_config_clear_removes_file(isolated_config: Path) -> None:
    isolated_config.parent.mkdir(parents=True)
    isolated_config.write_text("[registry]\n")

    result = runner.invoke(app, ["config", "--clear", "--show-path"])

    assert result.exit_code == 0
    assert "Registry configuration deleted." in result.stdout
    assert f"Location: {isolated_config}" in result.stdout
    assert not isolated_config.exists()


def test_cli_config_clear_reports_missing_file(isolated_config: Path) -> None:
    result = runner.invoke(app, ["config", "--clear"])

    assert result.exit_code == 0
    assert "No registry configuration found to delete." in result.stdout


def test_cli_config_clear_errors_with_additional_options(isolated_config: Path) -> None:
    result = runner.invoke(
        app,
        [
            "config",
            "--clear",
            "--url",
            "registry.example.com",
        ],
    )

    assert result.exit_code == 1
    assert "Cannot combine credential options with --clear." in (result.stderr or "")
