"""Helpers for interacting with the WalkAI secrets API."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from walkai.configuration import WalkAIAPIConfig


class SecretsError(RuntimeError):
    """Raised when a secrets API call fails."""


def _base_url(api: WalkAIAPIConfig) -> str:
    return api.url.rstrip("/")


def _auth_headers(api: WalkAIAPIConfig) -> dict[str, str]:
    return {"Authorization": f"Bearer {api.pat}"}


def _handle_response_error(
    response: httpx.Response, action: str, *, default: str | None = None
) -> None:
    if response.status_code < 400:
        return

    detail = response.text.strip() or default or f"HTTP {response.status_code}"
    raise SecretsError(f"{action}: {detail}")


def list_secrets(
    api: WalkAIAPIConfig, *, timeout: float = 30.0
) -> list[dict[str, Any]]:
    """Fetch the available secrets."""

    endpoint = f"{_base_url(api)}/secrets/"

    try:
        response = httpx.get(endpoint, headers=_auth_headers(api), timeout=timeout)
    except httpx.RequestError as exc:  # pragma: no cover - network failure guard
        raise SecretsError(f"Failed to reach WalkAI API: {exc}") from exc

    _handle_response_error(response, "Failed to list secrets")

    try:
        payload = response.json()
    except ValueError as exc:
        raise SecretsError("Secrets API returned invalid JSON.") from exc

    if not isinstance(payload, list):
        raise SecretsError("Secrets API returned an unexpected payload.")

    validated: list[dict[str, Any]] = []
    for entry in payload:
        if not isinstance(entry, dict) or "name" not in entry:
            raise SecretsError("Secrets API returned an unexpected entry.")
        validated.append({"name": str(entry["name"])})
    return validated


def get_secret(
    api: WalkAIAPIConfig,
    *,
    name: str,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Fetch a single secret by name."""

    endpoint = f"{_base_url(api)}/secrets/{name}"

    try:
        response = httpx.get(
            endpoint,
            headers=_auth_headers(api),
            timeout=timeout,
        )
    except httpx.RequestError as exc:  # pragma: no cover - network failure guard
        raise SecretsError(f"Failed to reach WalkAI API: {exc}") from exc

    if response.status_code == 404:
        raise SecretsError(f"Secret '{name}' was not found.")

    _handle_response_error(response, "Failed to fetch secret")

    try:
        payload = response.json()
    except ValueError as exc:
        raise SecretsError("Secrets API returned invalid JSON.") from exc

    if not isinstance(payload, dict):
        raise SecretsError("Secrets API returned an unexpected payload.")

    raw_keys = payload.get("keys") or []
    if not isinstance(raw_keys, list):
        raise SecretsError("Secrets API returned an unexpected keys payload.")

    keys: list[str] = []
    for entry in raw_keys:
        if not isinstance(entry, str):
            raise SecretsError("Secrets API returned an unexpected keys payload.")
        keys.append(entry)

    secret_name = payload.get("name", name)
    return {"name": str(secret_name), "keys": keys}


def create_secret(
    api: WalkAIAPIConfig,
    *,
    name: str,
    data: dict[str, str],
    timeout: float = 30.0,
) -> None:
    """Create or replace a secret."""

    endpoint = f"{_base_url(api)}/secrets/"
    payload = {"name": name, "data": data}

    try:
        response = httpx.post(
            endpoint,
            json=payload,
            headers=_auth_headers(api),
            timeout=timeout,
        )
    except httpx.RequestError as exc:  # pragma: no cover - network failure guard
        raise SecretsError(f"Failed to reach WalkAI API: {exc}") from exc

    _handle_response_error(response, "Failed to create secret")


def delete_secret(api: WalkAIAPIConfig, *, name: str, timeout: float = 30.0) -> None:
    """Delete an existing secret."""

    endpoint = f"{_base_url(api)}/secrets/{name}"

    try:
        response = httpx.delete(
            endpoint,
            headers=_auth_headers(api),
            timeout=timeout,
        )
    except httpx.RequestError as exc:  # pragma: no cover - network failure guard
        raise SecretsError(f"Failed to reach WalkAI API: {exc}") from exc

    if response.status_code == 204:
        return

    _handle_response_error(
        response, "Failed to delete secret", default="Secret not found."
    )


def parse_env_file(path: Path) -> dict[str, str]:
    """Parse a .env style file into a dictionary."""

    data: dict[str, str] = {}
    for idx, raw_line in enumerate(path.read_text().splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        if line.lower().startswith("export "):
            line = line[7:].lstrip()

        if "=" not in line:
            raise SecretsError(f"Invalid line {idx} in {path}: missing '='.")

        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            raise SecretsError(f"Invalid line {idx} in {path}: missing key.")

        value = value.strip()
        if value and value[0] in {"'", '"'} and value[-1:] == value[0]:
            value = value[1:-1]

        data[key] = value

    return data
