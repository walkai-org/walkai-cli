"""Tests for the walkai.build helpers."""

from pathlib import Path

import pytest
import tomllib

import walkai.build as build
from walkai.build import BuildError


@pytest.fixture
def project_factory(tmp_path: Path):
    """Return a helper that creates a minimal walkai project."""

    def factory(
        *,
        name: str = "demo",
        entrypoint: str = "python main.py",
        os_dependencies: list[str] | None = None,
        env_file: str | None = None,
    ) -> Path:
        project_dir = tmp_path / name
        project_dir.mkdir()

        deps_literal = ", ".join(f'"{dep}"' for dep in (os_dependencies or []))
        deps_value = f"[{deps_literal}]" if deps_literal else "[]"

        lines = [
            "[project]",
            f'name = "{name}"',
            "[tool.walkai]",
            f'entrypoint = "{entrypoint}"',
            f"os_dependencies = {deps_value}",
        ]

        if env_file is not None:
            lines.append(f'env_file = "{env_file}"')

        (project_dir / "pyproject.toml").write_text("\n".join(lines) + "\n")
        (project_dir / "main.py").write_text("print('hello from walkai')\n")

        if env_file is not None:
            (project_dir / env_file).write_text("FOO=bar\n")

        return project_dir

    return factory


def test_write_heroku_project_descriptor_generates_expected_structure(
    tmp_path: Path,
) -> None:
    context = tmp_path
    build._write_heroku_project_descriptor(context, (" git ", "curl", "git"))

    content = (context / "project.toml").read_text()
    parsed = tomllib.loads(content)

    assert parsed["_"]["schema-version"] == "0.2"
    install_entries = parsed["com"]["heroku"]["buildpacks"]["deb-packages"]["install"]
    assert install_entries == [
        {"name": "git", "force": True},
        {"name": "curl", "force": True},
    ]


def test_write_heroku_project_descriptor_raises_when_file_exists(
    tmp_path: Path,
) -> None:
    descriptor = tmp_path / "project.toml"
    descriptor.write_text("# existing descriptor\n")

    with pytest.raises(BuildError, match="project.toml"):
        build._write_heroku_project_descriptor(tmp_path, ("git",))


def test_build_image_runs_pack_with_default_image(
    monkeypatch: pytest.MonkeyPatch, project_factory
) -> None:
    project_dir = project_factory()

    captured: dict[str, list[str]] = {}

    def fake_run(cmd: list[str], *, check: bool) -> None:  # type: ignore[override]
        captured["cmd"] = cmd

    monkeypatch.setattr(build.subprocess, "run", fake_run)

    result = build.build_image(project_dir)

    assert result == "walkai/demo:latest"
    assert captured["cmd"][0:2] == ["pack", "build"]
    assert "--builder" in captured["cmd"]
    builder_index = captured["cmd"].index("--builder") + 1
    assert captured["cmd"][builder_index] == build.DEFAULT_BUILDER
    assert all("BP_APT_PACKAGES" not in part for part in captured["cmd"])


def test_build_image_rejects_existing_project_descriptor(
    monkeypatch: pytest.MonkeyPatch, project_factory
) -> None:
    project_dir = project_factory(os_dependencies=["git"])
    (project_dir / "project.toml").write_text("already here\n")

    def fake_run(cmd: list[str], *, check: bool) -> None:  # type: ignore[override]
        raise AssertionError("pack should not start when project.toml exists")

    monkeypatch.setattr(build.subprocess, "run", fake_run)

    with pytest.raises(BuildError, match="project.toml"):
        build.build_image(project_dir)


def test_build_image_env_override_missing_file(project_factory) -> None:
    project_dir = project_factory()
    missing = project_dir / "missing.env"

    with pytest.raises(
        BuildError, match="Environment file"
    ):  # message mentions missing file
        build.build_image(project_dir, env_file_override=missing)


def test_build_image_returns_custom_image(
    monkeypatch: pytest.MonkeyPatch, project_factory
) -> None:
    project_dir = project_factory()

    monkeypatch.setattr(build.subprocess, "run", lambda *args, **kwargs: None)

    result = build.build_image(project_dir, image="custom/image:tag")
    assert result == "custom/image:tag"
