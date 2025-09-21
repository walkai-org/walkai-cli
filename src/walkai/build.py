"""Image build helpers backed by the pack CLI."""

import shutil
import subprocess
from collections.abc import Iterable
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from walkai.project import (
    ProjectConfigError,
    WalkAIProjectConfig,
    load_project_config,
)

DEFAULT_BUILDER = "heroku/builder:24"


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


def _write_heroku_project_descriptor(context: Path, packages: tuple[str, ...]) -> None:
    """Ensure project.toml declares the Debian packages for Heroku builds."""

    normalised_packages = [pkg.strip() for pkg in packages if pkg.strip()]
    seen: set[str] = set()
    deduped = [pkg for pkg in normalised_packages if not (pkg in seen or seen.add(pkg))]
    if not deduped:
        return

    descriptor_path = context / "project.toml"
    if descriptor_path.exists():
        raise BuildError(
            f"walkai manages project.toml automatically but found one already present at {descriptor_path}. "
            "Please remove it so the build can proceed."
        )
    document: dict[str, Any] = {}

    entries = [{"name": pkg, "force": True} for pkg in deduped]

    document["_"] = {"schema-version": "0.2"}
    document["com.heroku.buildpacks.deb-packages"] = {"install": entries}

    descriptor_path.write_text(_dump_toml(document) + "\n")


def _dump_toml(document: dict[str, Any]) -> str:
    """Serialize a minimal subset of TOML for the project descriptor."""

    lines: list[str] = []

    def serialize_value(value: Any) -> str:
        if isinstance(value, str):
            escaped = value.replace("\\", "\\\\").replace('"', '\\"')
            return f'"{escaped}"'
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (int, float)):
            return str(value)
        if isinstance(value, list):
            inner = ", ".join(serialize_value(item) for item in value)
            return f"[{inner}]"
        if isinstance(value, dict):
            parts = [f"{key} = {serialize_value(val)}" for key, val in value.items()]
            return "{ " + ", ".join(parts) + " }"
        raise ValueError(f"Unsupported TOML value type: {type(value)!r}")

    def write_table(table: dict[str, Any], path: tuple[str, ...]) -> None:
        scalar_items: list[tuple[str, Any]] = []
        subtables: list[tuple[str, dict[str, Any]]] = []

        for key, value in table.items():
            if isinstance(value, dict):
                subtables.append((key, value))
            else:
                scalar_items.append((key, value))

        if path:
            lines.append("")
            lines.append(f"[{'.'.join(path)}]")

        for key, value in scalar_items:
            lines.append(f"{key} = {serialize_value(value)}")

        for key, value in subtables:
            write_table(value, (*path, key))

    write_table(document, ())

    return "\n".join(lines).lstrip("\n")


def _build_command(
    image: str,
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
        DEFAULT_BUILDER,
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
    env_file_override: Path | None = None,
) -> str:
    """Build a container image for the given project directory."""

    try:
        config = load_project_config(project_dir)
    except ProjectConfigError as exc:
        raise BuildError(str(exc)) from exc

    target_image = image or config.default_image()

    env_file = env_file_override or config.env_file
    if env_file is not None and not env_file.exists():
        raise BuildError(f"Environment file '{env_file}' not found.")

    is_heroku_builder = DEFAULT_BUILDER.lower().startswith("heroku/")
    env_values: list[tuple[str, str]] = []
    if config.os_dependencies and not is_heroku_builder:
        env_values.append(("BP_APT_PACKAGES", " ".join(config.os_dependencies)))

    with TemporaryDirectory() as build_context:
        context_path = Path(build_context)
        _copy_project_sources(config, context_path)

        if config.os_dependencies and is_heroku_builder:
            _write_heroku_project_descriptor(context_path, config.os_dependencies)

        command = _build_command(
            image=target_image,
            env_file=env_file,
            build_path=context_path,
            env_variables=env_values,
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
