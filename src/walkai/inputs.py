"""Helpers for interacting with WalkAI input volumes."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

import httpx

from walkai.configuration import WalkAIAPIConfig


class InputError(RuntimeError):
    """Raised when an input volume API call fails."""


def _base_url(api: WalkAIAPIConfig) -> str:
    return api.url.rstrip("/")


def _auth_headers(api: WalkAIAPIConfig) -> dict[str, str]:
    return {"Authorization": f"Bearer {api.pat}"}


def list_input_volumes(
    api: WalkAIAPIConfig, *, timeout: float = 30.0
) -> list[dict[str, Any]]:
    """Fetch input volumes available to the user."""

    endpoint = f"{_base_url(api)}/volumes/"

    try:
        response = httpx.get(
            endpoint,
            headers=_auth_headers(api),
            params={"is_input": True},
            timeout=timeout,
        )
    except httpx.RequestError as exc:  # pragma: no cover - network failure guard
        raise InputError(f"Failed to reach WalkAI API: {exc}") from exc

    if response.status_code >= 400:
        detail = response.text.strip() or f"HTTP {response.status_code}"
        raise InputError(f"Failed to list input volumes: {detail}")

    try:
        payload = response.json()
    except ValueError as exc:
        raise InputError("Input volumes API returned invalid JSON.") from exc

    if not isinstance(payload, list):
        raise InputError("Input volumes API returned an unexpected payload.")

    volumes: list[dict[str, Any]] = []
    for entry in payload:
        if not isinstance(entry, dict):
            raise InputError("Input volumes API returned an unexpected entry.")

        try:
            volume_id = int(entry["id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise InputError(
                "Input volumes API returned an invalid volume id."
            ) from exc

        name = entry.get("pvc_name") or entry.get("name")
        if not isinstance(name, str) or not name.strip():
            raise InputError("Input volumes API returned an invalid volume name.")

        try:
            size = int(entry["size"])
        except (KeyError, TypeError, ValueError) as exc:
            raise InputError(
                "Input volumes API returned an invalid volume size."
            ) from exc

        volumes.append({"id": volume_id, "name": name, "size": size})

    return volumes


def list_volume_objects(
    api: WalkAIAPIConfig, *, volume_id: int, timeout: float = 30.0
) -> list[dict[str, Any]]:
    """Fetch objects stored inside a volume."""

    endpoint = f"{_base_url(api)}/volumes/{volume_id}/objects"

    try:
        response = httpx.get(
            endpoint,
            headers=_auth_headers(api),
            timeout=timeout,
        )
    except httpx.RequestError as exc:  # pragma: no cover - network failure guard
        raise InputError(f"Failed to reach WalkAI API: {exc}") from exc

    if response.status_code == 404:
        raise InputError(f"Volume '{volume_id}' was not found.")

    if response.status_code >= 400:
        detail = response.text.strip() or f"HTTP {response.status_code}"
        raise InputError(f"Failed to list volume objects: {detail}")

    try:
        payload = response.json()
    except ValueError as exc:
        raise InputError("Volume objects API returned invalid JSON.") from exc

    if not isinstance(payload, dict):
        raise InputError("Volume objects API returned an unexpected payload.")

    raw_objects = payload.get("objects")
    if raw_objects is None:
        return []
    if not isinstance(raw_objects, list):
        raise InputError("Volume objects API returned an unexpected objects payload.")

    objects: list[dict[str, Any]] = []
    for entry in raw_objects:
        if not isinstance(entry, dict) or "key" not in entry:
            raise InputError("Volume objects API returned an unexpected object entry.")

        key = entry["key"]
        if not isinstance(key, str):
            raise InputError("Volume objects API returned an invalid object key.")

        size_raw = entry.get("size")
        try:
            size = int(size_raw) if size_raw is not None else 0
        except (TypeError, ValueError) as exc:
            raise InputError(
                "Volume objects API returned an invalid object size."
            ) from exc

        last_modified = entry.get("last_modified")
        if last_modified is not None and not isinstance(last_modified, str):
            last_modified = str(last_modified)

        etag = entry.get("etag")
        if etag is not None and not isinstance(etag, str):
            etag = str(etag)

        objects.append(
            {
                "key": key,
                "size": size,
                "last_modified": last_modified,
                "etag": etag,
            }
        )

    return objects


def create_input_volume(
    api: WalkAIAPIConfig, *, size: int, timeout: float = 30.0
) -> dict[str, Any]:
    """Create a new input volume and return its metadata."""

    if size <= 0:
        raise InputError("Input volume size must be greater than zero.")

    endpoint = f"{_base_url(api)}/volumes/inputs"
    payload = {"storage": size}

    try:
        response = httpx.post(
            endpoint,
            json=payload,
            headers=_auth_headers(api),
            timeout=timeout,
        )
    except httpx.RequestError as exc:  # pragma: no cover - network failure guard
        raise InputError(f"Failed to reach WalkAI API: {exc}") from exc

    if response.status_code >= 400:
        detail = response.text.strip() or f"HTTP {response.status_code}"
        raise InputError(f"Failed to create input volume: {detail}")

    try:
        payload = response.json()
    except ValueError as exc:
        raise InputError("Create input volume API returned invalid JSON.") from exc

    if not isinstance(payload, dict):
        raise InputError("Create input volume API returned an unexpected payload.")

    raw_volume = payload.get("volume")
    if not isinstance(raw_volume, dict):
        raise InputError(
            "Create input volume API returned an unexpected volume payload."
        )

    try:
        volume_id = int(raw_volume["id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise InputError(
            "Create input volume API returned an invalid volume id."
        ) from exc

    name = raw_volume.get("pvc_name") or raw_volume.get("name")
    if not isinstance(name, str) or not name.strip():
        raise InputError("Create input volume API returned an invalid volume name.")

    try:
        volume_size = int(raw_volume["size"])
    except (KeyError, TypeError, ValueError) as exc:
        raise InputError(
            "Create input volume API returned an invalid volume size."
        ) from exc

    key_prefix = raw_volume.get("key_prefix")
    if key_prefix is not None and not isinstance(key_prefix, str):
        key_prefix = str(key_prefix)

    is_input = raw_volume.get("is_input")
    if is_input is not None:
        is_input = bool(is_input)

    return {
        "id": volume_id,
        "name": name,
        "size": volume_size,
        "key_prefix": key_prefix,
        "is_input": is_input,
    }


def request_input_upload_urls(
    api: WalkAIAPIConfig,
    *,
    volume_id: int,
    filenames: Iterable[str],
    timeout: float = 30.0,
) -> list[str]:
    """Request presigned URLs for uploading files to an input volume."""

    names = [name for name in filenames if name]
    if not names:
        raise InputError("At least one file name must be provided.")

    endpoint = f"{_base_url(api)}/volumes/inputs/presigneds"
    payload = {"volume_id": volume_id, "file_names": names}

    try:
        response = httpx.post(
            endpoint,
            json=payload,
            headers=_auth_headers(api),
            timeout=timeout,
        )
    except httpx.RequestError as exc:  # pragma: no cover - network failure guard
        raise InputError(f"Failed to reach WalkAI API: {exc}") from exc

    if response.status_code >= 400:
        detail = response.text.strip() or f"HTTP {response.status_code}"
        raise InputError(f"Failed to request upload URLs: {detail}")

    try:
        payload = response.json()
    except ValueError as exc:
        raise InputError("Request upload URLs API returned invalid JSON.") from exc

    if not isinstance(payload, dict):
        raise InputError("Request upload URLs API returned an unexpected payload.")

    presigneds = payload.get("presigneds")
    if presigneds is None:
        return []
    if not isinstance(presigneds, list):
        raise InputError(
            "Request upload URLs API returned an unexpected presigneds payload."
        )

    urls: list[str] = []
    for entry in presigneds:
        if not isinstance(entry, str) or not entry.strip():
            raise InputError(
                "Request upload URLs API returned an invalid presigned URL."
            )
        urls.append(entry)

    return urls


def upload_files_to_presigned(
    urls: list[str],
    files: list[Path],
    *,
    timeout: float = 60.0,
) -> None:
    """Upload files to their corresponding presigned URLs."""

    if len(urls) != len(files):
        raise InputError(
            "The number of presigned URLs does not match the number of files."
        )

    for idx, (url, path) in enumerate(zip(urls, files, strict=False), start=1):
        if not isinstance(url, str) or not url.strip():
            raise InputError("Encountered an invalid presigned URL.")

        try:
            with path.open("rb") as handle:
                response = httpx.put(
                    url,
                    content=handle,
                    headers={"Content-Type": "application/octet-stream"},
                    timeout=timeout,
                )
        except FileNotFoundError as exc:
            raise InputError(f"File not found: {path}") from exc
        except httpx.RequestError as exc:  # pragma: no cover - network failure guard
            raise InputError(f"Failed to upload file {path.name}: {exc}") from exc

        if response.status_code >= 400:
            detail = response.text.strip() or f"HTTP {response.status_code}"
            raise InputError(f"Upload failed for {path.name} (item {idx}): {detail}")
