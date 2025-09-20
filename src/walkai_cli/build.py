"""Image build helpers backed by the pack CLI."""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Iterable
from pathlib import Path
from tempfile import TemporaryDirectory

from .project import ProjectConfigError, WalkAIProjectConfig, load_project_config

DEFAULT_BUILDER = "gcr.io/paketo-buildpacks/builder:base"
DEFAULT_PYTHON_VERSION = "3.11.x"


class BuildError(RuntimeError):
    """Raised when the container image build fails."""


def _copy_project_sources(project: WalkAIProjectConfig, destination: Path) -> None:
    """Copy the project sources to the temporary build context."""

    def ignore(
        directory: str, names: list[str]
    ) -> set[str]:  # pragma: no cover - passthrough
        # Skip common directories that bloat the build context.
        exclusions = {
            ".git",
            "__pycache__",
            ".mypy_cache",
            ".pytest_cache",
            "env",
            ".venv",
        }
        return {name for name in names if name in exclusions}

    for item in project.root.iterdir():
        dest = destination / item.name
        if item.is_dir():
            shutil.copytree(item, dest, dirs_exist_ok=True, ignore=ignore)
        else:
            shutil.copy2(item, dest)

    procfile = destination / "Procfile"
    procfile.write_text(f"web: {project.entrypoint}\n")


def _build_command(
    image: str,
    builder: str,
    project: WalkAIProjectConfig,
    env_variables: Iterable[tuple[str, str]],
    build_path: Path,
    env_file: Path | None,
) -> list[str]:
    """Assemble the pack build command."""

    command: list[str] = [
        "pack",
        "build",
        image,
        "--path",
        str(build_path),
        "--builder",
        builder,
        "--pull-policy",
        "if-not-present",
    ]

    for key, value in env_variables:
        command.extend(["--env", f"{key}={value}"])

    if env_file is not None:
        command.extend(["--env-file", str(env_file)])

    return command


def build_image(
    project_dir: Path,
    image: str | None = None,
    *,
    builder: str = DEFAULT_BUILDER,
    python_version: str = DEFAULT_PYTHON_VERSION,
    env_file_override: Path | None = None,
) -> str:
    """Build a container image for the given project directory."""

    try:
        config = load_project_config(project_dir)
    except ProjectConfigError as exc:
        raise BuildError(str(exc)) from exc

    target_image = image or config.default_image()

    env_values: list[tuple[str, str]] = []
    if config.os_dependencies:
        env_values.append(("BP_APT_PACKAGES", " ".join(config.os_dependencies)))
    if python_version:
        env_values.append(("BP_PYTHON_VERSION", python_version))

    env_file = env_file_override or config.env_file
    if env_file is not None and not env_file.exists():
        raise BuildError(f"Environment file '{env_file}' not found.")

    with TemporaryDirectory() as build_context:
        context_path = Path(build_context)
        _copy_project_sources(config, context_path)

        command = _build_command(
            target_image, builder, config, env_values, context_path, env_file
        )

        try:
            subprocess.run(command, check=True)
        except FileNotFoundError as exc:  # pragma: no cover - direct subprocess failure
            raise BuildError(
                "The 'pack' CLI is not installed or not found in PATH."
            ) from exc
        except subprocess.CalledProcessError as exc:
            raise BuildError(
                f"pack build failed with exit code {exc.returncode}."
            ) from exc

    return target_image
