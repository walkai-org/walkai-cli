"""Helpers for managing Walkai CLI configuration."""

import os
import textwrap
import tomllib
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_config_dir


class ConfigError(RuntimeError):
    """Raised when the persisted configuration is invalid."""


@dataclass(slots=True)
class WalkAIAPIConfig:
    """Walkai API connection information."""

    url: str
    pat: str


@dataclass(slots=True)
class WalkAIConfig:
    """Full CLI configuration payload."""

    walkai_api: WalkAIAPIConfig


_CONFIG_DIR = Path(user_config_dir("walkai", "walkai"))
_CONFIG_FILE = _CONFIG_DIR / "config.toml"


def config_path() -> Path:
    """Return the path where the CLI configuration is stored."""

    return _CONFIG_FILE


def load_config() -> WalkAIConfig | None:
    """Load the saved CLI configuration, if present."""

    if not _CONFIG_FILE.exists():
        return None

    try:
        payload = tomllib.loads(_CONFIG_FILE.read_text())
    except tomllib.TOMLDecodeError as exc:  # type: ignore[attr-defined]
        raise ConfigError(f"Failed to parse configuration file: {exc}") from exc

    walkai_section = payload.get("walkai")
    if not isinstance(walkai_section, dict):
        raise ConfigError("Configuration file is missing the [walkai] section.")

    try:
        walkai_api_config = WalkAIAPIConfig(
            url=str(walkai_section["api_url"]),
            pat=str(walkai_section["pat"]),
        )
    except KeyError as exc:  # pragma: no cover - defensive guard
        raise ConfigError(
            f"Configuration file is missing the required field: walkai.{exc.args[0]}"
        ) from exc

    return WalkAIConfig(walkai_api=walkai_api_config)


def save_config(config: WalkAIConfig) -> Path:
    """Persist the given CLI configuration to disk."""

    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    walkai = config.walkai_api
    content = textwrap.dedent(
        f"""
        [walkai]
        api_url = \"{walkai.url}\"
        pat = \"{walkai.pat}\"
        """
    ).strip()

    _CONFIG_FILE.write_text(content + "\n")

    if os.name != "nt":  # tighten permissions on POSIX systems
        os.chmod(_CONFIG_FILE, 0o600)

    return _CONFIG_FILE


def delete_config() -> bool:
    """Delete the persisted configuration if it exists."""

    if not _CONFIG_FILE.exists():
        return False

    try:
        _CONFIG_FILE.unlink()
    except OSError as exc:  # pragma: no cover - defensive guard
        raise ConfigError(f"Failed to delete configuration file: {exc}") from exc

    return True
