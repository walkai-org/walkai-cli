"""Support for pushing images to a registry."""

import base64
import subprocess
from dataclasses import dataclass
from typing import Literal

import httpx

from walkai.configuration import WalkAIAPIConfig


class PushError(RuntimeError):
    """Raised when image push fails."""


ContainerClient = Literal["docker", "podman"]


@dataclass(slots=True)
class RegistryCredentials:
    """Registry connection information returned by the WalkAI API."""

    url: str
    username: str
    password: str


def fetch_registry_credentials(api_config: WalkAIAPIConfig) -> RegistryCredentials:
    """Request short-lived registry credentials from the WalkAI API."""

    base_url = api_config.url.rstrip("/")
    endpoint = f"{base_url}/registry"
    headers = {"Authorization": f"Bearer {api_config.pat}"}

    try:
        response = httpx.get(endpoint, headers=headers, timeout=30)
    except httpx.RequestError as exc:
        raise PushError(f"Failed to reach WalkAI API: {exc}") from exc

    if response.status_code >= 400:
        detail = response.text.strip() or f"HTTP {response.status_code}"
        raise PushError(f"Failed to obtain registry credentials: {detail}")

    try:
        payload = response.json()
    except ValueError as exc:
        raise PushError("WalkAI API returned malformed registry credentials.") from exc

    decoded = base64.b64decode(payload["token"]).decode("utf-8")
    username, password = decoded.split(":")

    try:
        return RegistryCredentials(
            url=str(payload["ecr_url"]),
            username=username,
            password=password,
        )

    except KeyError as exc:  # pragma: no cover - defensive guard
        raise PushError(
            f"WalkAI API response missing registry.{exc.args[0]} field."
        ) from exc


def normalise_registry_host(value: str) -> str:
    """Normalise the registry URL so it can be used with docker/podman."""

    cleaned = value.strip()
    if cleaned.startswith("https://"):
        cleaned = cleaned.removeprefix("https://")
    elif cleaned.startswith("http://"):
        cleaned = cleaned.removeprefix("http://")

    return cleaned.rstrip("/")


def push_image(
    local_image: str,
    credentials: RegistryCredentials,
    *,
    client: ContainerClient = "docker",
) -> str:
    """Push the given image to the configured registry.

    Returns the full remote image reference that was pushed.
    """

    remote_ref = credentials.url

    try:
        _login(client, credentials)
        remote_ref = _tag(client, local_image, credentials.url)
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


def _login(client: ContainerClient, credentials: RegistryCredentials) -> None:
    command = [
        client,
        "login",
        credentials.url,
        "--username",
        credentials.username,
        "--password-stdin",
    ]
    subprocess.run(command, check=True, input=credentials.password, text=True)


def _normalize_local_image_name(local: str) -> str:
    """Extract a tag-friendly name from the local image reference."""

    ref = local.strip()
    if not ref:
        raise PushError("Local image reference cannot be empty.")

    # Drop any digest suffix, e.g. example/image@sha256:...
    ref = ref.split("@", 1)[0]

    # Keep only the final path component.
    if "/" in ref:
        ref = ref.rsplit("/", 1)[-1]

    # If there is a tag, it will appear after the final colon that follows the
    # last slash (ports in the registry host are already stripped above).
    if ":" in ref:
        ref = ref.split(":", 1)[0]

    if not ref:
        raise PushError(
            f"Could not derive image name from '{local}'. Please provide a valid image."
        )

    return ref


def _normalize_remote_repository(remote: str) -> str:
    """Return the remote repository without any tag or digest suffix."""

    ref = remote.strip()
    if not ref:
        raise PushError("Remote registry reference cannot be empty.")

    ref = ref.split("@", 1)[0]

    last_slash = ref.rfind("/")
    colon_after_slash = ref.rfind(":")

    if colon_after_slash > last_slash:
        ref = ref[:colon_after_slash]

    if not ref:
        raise PushError(f"Could not derive remote repository from '{remote}'.")

    return ref


def _tag(client: ContainerClient, local: str, remote: str) -> str:
    remote_repo = _normalize_remote_repository(remote)
    remote_ref = f"{remote_repo}:{_normalize_local_image_name(local)}"
    subprocess.run([client, "tag", local, remote_ref], check=True)
    return remote_ref


def _push(client: ContainerClient, remote: str) -> None:
    subprocess.run([client, "push", remote], check=True)
