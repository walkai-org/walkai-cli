"""Support for pushing images to a registry."""
import subprocess
from typing import Literal

from walkai.configuration import RegistryConfig, normalise_registry_host


class PushError(RuntimeError):
    """Raised when image push fails."""


ContainerClient = Literal["docker", "podman"]


def push_image(
    local_image: str,
    config: RegistryConfig,
    *,
    repository: str | None = None,
    client: ContainerClient = "docker",
) -> str:
    """Push the given image to the configured registry.

    Returns the full remote image reference that was pushed.
    """

    registry = normalise_registry_host(config.url)
    if not registry:
        raise PushError("Registry URL may not be empty.")

    host, remote_ref = _compose_remote_ref(local_image, registry, repository)

    try:
        _login(client, host, config)
        _tag(client, local_image, remote_ref)
        _push(client, remote_ref)
    except subprocess.CalledProcessError as exc:
        raise PushError(
            f"{client} command failed with exit code {exc.returncode}."
        ) from exc
    except FileNotFoundError as exc:  # pragma: no cover - depends on environment
        raise PushError(
            f"The '{client}' CLI is not installed or not present in PATH."
        ) from exc

    return remote_ref


def _compose_remote_ref(
    local: str, registry: str, repository: str | None
) -> tuple[str, str]:
    host, _, namespace = registry.partition("/")
    if not host:
        raise PushError("Registry host is missing from the configured URL.")

    candidate = (repository or local).lstrip("/")
    if namespace:
        namespace = namespace.rstrip("/")
        candidate = f"{namespace}/{candidate}" if candidate else namespace

    remote_ref = f"{host}/{candidate}" if candidate else host
    return host, remote_ref


def _login(client: ContainerClient, registry_host: str, config: RegistryConfig) -> None:
    command = [
        client,
        "login",
        registry_host,
        "--username",
        config.username,
        "--password-stdin",
    ]
    subprocess.run(command, check=True, input=config.password, text=True)


def _tag(client: ContainerClient, local: str, remote: str) -> None:
    subprocess.run([client, "tag", local, remote], check=True)


def _push(client: ContainerClient, remote: str) -> None:
    subprocess.run([client, "push", remote], check=True)
