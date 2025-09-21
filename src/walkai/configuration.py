"""Helpers for managing Walkai registry configuration."""

import os
import textwrap
from dataclasses import dataclass
from pathlib import Path

import tomllib
from platformdirs import user_config_dir


class ConfigError(RuntimeError):
    """Raised when the persisted configuration is invalid."""


@dataclass(slots=True)
class RegistryConfig:
    """Container registry connection information."""

    url: str
    username: str
    password: str


_CONFIG_DIR = Path(user_config_dir("walkai", "walkai"))
_CONFIG_FILE = _CONFIG_DIR / "config.toml"


def config_path() -> Path:
    """Return the path where the registry configuration is stored."""

    return _CONFIG_FILE


def load_config() -> RegistryConfig | None:
    """Load the saved registry configuration, if present."""

    if not _CONFIG_FILE.exists():
        return None

    try:
        payload = tomllib.loads(_CONFIG_FILE.read_text())
    except tomllib.TOMLDecodeError as exc:  # type: ignore[attr-defined]
        raise ConfigError(f"Failed to parse configuration file: {exc}") from exc

    registry_section = payload.get("registry")
    if not isinstance(registry_section, dict):
        raise ConfigError("Configuration file is missing the [registry] section.")

    try:
        return RegistryConfig(
            url=str(registry_section["url"]),
            username=str(registry_section["username"]),
            password=str(registry_section["password"]),
        )
    except KeyError as exc:  # pragma: no cover - defensive guard
        raise ConfigError(
            f"Configuration file is missing the required field: {exc.args[0]}"
        ) from exc


def save_config(config: RegistryConfig) -> Path:
    """Persist the given registry configuration to disk."""

    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent(
        f"""
        [registry]
        url = \"{config.url}\"
        username = \"{config.username}\"
        password = \"{config.password}\"
        """
    ).strip()

    _CONFIG_FILE.write_text(content + "\n")

    if os.name != "nt":  # tighten permissions on POSIX systems
        os.chmod(_CONFIG_FILE, 0o600)

    return _CONFIG_FILE


def normalise_registry_host(value: str) -> str:
    """Normalise the registry URL so it can be used with docker/podman."""

    cleaned = value.strip()
    if cleaned.startswith("https://"):
        cleaned = cleaned.removeprefix("https://")
    elif cleaned.startswith("http://"):
        cleaned = cleaned.removeprefix("http://")

    return cleaned.rstrip("/")
