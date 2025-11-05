"""Utilities to inspect a target project's pyproject configuration."""

import re
import tomllib
from pathlib import Path


class ProjectConfigError(RuntimeError):
    """Raised when the target pyproject.toml is missing required information."""


class WalkAIProjectConfig:
    """Container build configuration extracted from tool.walkai."""

    def __init__(
        self,
        project_name: str,
        entrypoint: str,
        os_dependencies: tuple[str, ...],
        root: Path,
        gpu: str | None = None,
        inputs: tuple[Path, ...] = (),
        storage: int = 1,
    ):
        self.project_name = project_name
        self.entrypoint = entrypoint
        self.os_dependencies = os_dependencies
        self.root = root
        self.gpu = gpu
        self.inputs = inputs
        self.storage = storage

    def default_image(self) -> str:
        """Return an opinionated default image name for the project."""

        sanitized = re.sub(r"[^a-z0-9_.-]+", "-", self.project_name.lower()).strip("-")
        base = sanitized or self.root.name.lower()
        return f"walkai/{base}:latest"


def load_project_config(project_dir: Path) -> WalkAIProjectConfig:
    """Read the walkai configuration from a project's pyproject.toml."""

    project_dir = project_dir.resolve()
    pyproject_path = project_dir / "pyproject.toml"
    if not pyproject_path.exists():
        raise ProjectConfigError(f"No pyproject.toml found at {pyproject_path}.")

    try:
        document = tomllib.loads(pyproject_path.read_text())
    except tomllib.TOMLDecodeError as exc:  # type: ignore[attr-defined]
        raise ProjectConfigError(f"Failed to parse {pyproject_path}: {exc}") from exc

    project_table = document.get("project", {})
    project_name = str(project_table.get("name") or project_dir.name)

    walkai_section = (
        document.get("tool", {}).get("walkai")
        if isinstance(document.get("tool"), dict)
        else None
    )
    if not isinstance(walkai_section, dict):
        raise ProjectConfigError(
            "The pyproject.toml is missing the [tool.walkai] section."
        )

    entrypoint = walkai_section.get("entrypoint")
    if not entrypoint or not isinstance(entrypoint, str):
        raise ProjectConfigError(
            "The [tool.walkai] section must define an 'entrypoint' string."
        )

    gpu_value = walkai_section.get("gpu")
    gpu: str | None = None
    if not gpu_value or not isinstance(gpu_value, str) or not gpu_value.strip():
        raise ProjectConfigError("The 'gpu' field must be a non-empty string.")

    gpu = gpu_value.strip()

    os_dependencies = walkai_section.get("os_dependencies", [])
    if not isinstance(os_dependencies, list) or not all(
        isinstance(item, str) for item in os_dependencies
    ):
        raise ProjectConfigError(
            "The 'os_dependencies' field must be a list of strings if provided."
        )

    inputs_value = walkai_section.get("inputs", [])
    inputs: list[Path] = []
    if inputs_value:
        if not isinstance(inputs_value, list) or not all(
            isinstance(item, str) for item in inputs_value
        ):
            raise ProjectConfigError(
                "The 'inputs' field must be a list of relative paths if provided."
            )
        for item in inputs_value:
            resolved = (project_dir / item).resolve()
            if not resolved.exists():
                raise ProjectConfigError(
                    f"Input path declared at {resolved} does not exist."
                )
            inputs.append(resolved)

    storage_value = walkai_section.get("storage")
    if storage_value is None:
        raise ProjectConfigError(
            "The [tool.walkai] section must define a 'storage' integer."
        )
    if not isinstance(storage_value, int):
        raise ProjectConfigError("The 'storage' field must be an integer.")
    if storage_value <= 0:
        raise ProjectConfigError("The 'storage' field must be greater than zero.")

    return WalkAIProjectConfig(
        project_name=project_name,
        entrypoint=entrypoint.strip(),
        os_dependencies=tuple(dep.strip() for dep in os_dependencies),
        root=project_dir,
        gpu=gpu,
        inputs=tuple(inputs),
        storage=storage_value,
    )
