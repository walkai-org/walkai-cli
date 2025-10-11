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
class RegistryConfig:
    """Container registry connection information."""

    url: str
    username: str
    password: str


@dataclass(slots=True)
class WalkAIAPIConfig:
    """Walkai API connection information."""

    url: str
    pat: str


@dataclass(slots=True)
class WalkAIConfig:
    """Full CLI configuration payload."""

    registry: RegistryConfig
    walkai_api: WalkAIAPIConfig | None = None


_CONFIG_DIR = Path(user_config_dir("walkai", "walkai"))
_CONFIG_FILE = _CONFIG_DIR / "config.toml"


def config_path() -> Path:
    """Return the path where the registry configuration is stored."""

    return _CONFIG_FILE


def load_config() -> WalkAIConfig | None:
    """Load the saved CLI configuration, if present."""

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
        registry_config = RegistryConfig(
            url=str(registry_section["url"]),
            username=str(registry_section["username"]),
            password=str(registry_section["password"]),
        )
    except KeyError as exc:  # pragma: no cover - defensive guard
        raise ConfigError(
            f"Configuration file is missing the required field: {exc.args[0]}"
        ) from exc

    walkai_section = payload.get("walkai")
    walkai_api_config: WalkAIAPIConfig | None = None
    if walkai_section is not None:
        if not isinstance(walkai_section, dict):
            raise ConfigError("Configuration file has an invalid [walkai] section.")
        try:
            walkai_api_config = WalkAIAPIConfig(
                url=str(walkai_section["api_url"]),
                pat=str(walkai_section["pat"]),
            )
        except KeyError as exc:  # pragma: no cover - defensive guard
            raise ConfigError(
                "Configuration file is missing the required field: "
                f"walkai.{exc.args[0]}"
            ) from exc

    return WalkAIConfig(registry=registry_config, walkai_api=walkai_api_config)


def save_config(config: WalkAIConfig) -> Path:
    """Persist the given CLI configuration to disk."""

    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    registry = config.registry
    content = textwrap.dedent(
        f"""
        [registry]
        url = \"{registry.url}\"
        username = \"{registry.username}\"
        password = \"{registry.password}\"
        """
    ).strip()

    if config.walkai_api is not None:
        walkai = config.walkai_api
        walkai_section = textwrap.dedent(
            f"""

            [walkai]
            api_url = \"{walkai.url}\"
            pat = \"{walkai.pat}\"
            """
        ).rstrip()
        content = content + walkai_section

    _CONFIG_FILE.write_text(content + "\n")

    if os.name != "nt":  # tighten permissions on POSIX systems
        os.chmod(_CONFIG_FILE, 0o600)

    return _CONFIG_FILE


def delete_config() -> bool:
    """Delete the persisted registry configuration if it exists."""

    if not _CONFIG_FILE.exists():
        return False

    try:
        _CONFIG_FILE.unlink()
    except OSError as exc:  # pragma: no cover - defensive guard
        raise ConfigError(f"Failed to delete configuration file: {exc}") from exc

    return True


def normalise_registry_host(value: str) -> str:
    """Normalise the registry URL so it can be used with docker/podman."""

    cleaned = value.strip()
    if cleaned.startswith("https://"):
        cleaned = cleaned.removeprefix("https://")
    elif cleaned.startswith("http://"):
        cleaned = cleaned.removeprefix("http://")

    return cleaned.rstrip("/")
