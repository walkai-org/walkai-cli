"""Tests for the Kubernetes job command."""

from __future__ import annotations

import os
import tarfile
from pathlib import Path

import yaml
from typer.testing import CliRunner

from walkai.main import app

runner = CliRunner()


def _create_project(
    root: Path,
    *,
    name: str = "demo",
    entrypoint: str = "python main.py",
    gpu: str | None = None,
    env_vars: dict[str, str] | None = None,
    inputs: dict[str, str] | None = None,
) -> Path:
    project_dir = root / name
    project_dir.mkdir()

    lines = [
        "[project]",
        f'name = "{name}"',
        "[tool.walkai]",
        f'entrypoint = "{entrypoint}"',
        "os_dependencies = []",
    ]
    env_file_name: str | None = None
    if env_vars:
        env_file_name = "job.env"
        lines.append(f'env_file = "{env_file_name}"')
    if gpu is not None:
        lines.append(f'gpu = "{gpu}"')
    if inputs:
        input_list = ", ".join(f'"{path}"' for path in inputs)
        lines.append(f"inputs = [{input_list}]")

    (project_dir / "pyproject.toml").write_text("\n".join(lines) + "\n")
    (project_dir / "main.py").write_text("print('.walkai job')\n")

    if env_file_name and env_vars:
        env_lines = [f"{key}={value}" for key, value in env_vars.items()]
        (project_dir / env_file_name).write_text("\n".join(env_lines) + "\n")

    if inputs:
        for relative_path, content in inputs.items():
            target_path = project_dir / relative_path
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(content)

    return project_dir


def test_job_command_emits_manifest_with_gpu(tmp_path: Path) -> None:
    project_dir = _create_project(
        tmp_path,
        gpu="1g.10gb",
        env_vars={"FOO": "bar", "BAR": "baz"},
        inputs={"datasets/sample.txt": "hello dataset\n"},
    )

    cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        result = runner.invoke(
            app,
            [
                "job",
                str(project_dir),
                "--image",
                "example/image:latest",
                "--input-size",
                "2Gi",
                "--output-size",
                "3Gi",
            ],
            catch_exceptions=False,
        )
    finally:
        os.chdir(cwd)

    assert result.exit_code == 0, result.stdout
    lines = result.stdout.splitlines()
    input_pvc_path = tmp_path / lines[0].split(" to ", 1)[1]
    archive_path = tmp_path / lines[1].split(" to ", 1)[1]
    manifest_yaml = "\n".join(lines[3:])
    documents = list(yaml.safe_load_all(manifest_yaml))
    assert len(documents) == 2
    manifest = documents[0]
    output_pvc_doc = documents[1]

    assert manifest["spec"]["backoffLimit"] == 0
    template = manifest["spec"]["template"]
    assert template["spec"]["restartPolicy"] == "Never"
    assert template["spec"].get("initContainers") is None
    assert template["spec"]["securityContext"]["fsGroup"] == 1000

    container = template["spec"]["containers"][0]
    assert container["image"] == "example/image:latest"
    assert container["resources"]["limits"] == {"nvidia.com/mig-1g.10gb": 1}
    env = {item["name"]: item["value"] for item in container["env"]}
    assert env == {"FOO": "bar", "BAR": "baz"}

    mount_paths = {m["mountPath"]: m for m in container["volumeMounts"]}
    assert mount_paths["/opt/input"]["readOnly"] is True
    assert mount_paths["/opt/output"]["name"] == "output"

    volumes = {v["name"]: v for v in template["spec"]["volumes"]}
    input_claim = volumes["input"]["persistentVolumeClaim"]["claimName"]
    output_claim = volumes["output"]["persistentVolumeClaim"]["claimName"]

    input_pvc_doc = yaml.safe_load(input_pvc_path.read_text())
    assert input_pvc_doc["metadata"]["name"] == input_claim
    assert input_pvc_doc["spec"]["resources"]["requests"]["storage"] == "2Gi"
    assert output_pvc_doc["metadata"]["name"] == output_claim
    assert output_pvc_doc["spec"]["resources"]["requests"]["storage"] == "3Gi"

    with tarfile.open(archive_path, "r:gz") as archive:
        members = archive.getnames()
        assert "datasets/sample.txt" in members
        extracted = archive.extractfile("datasets/sample.txt")
        assert extracted is not None
        assert extracted.read().decode() == "hello dataset\n"


def test_job_command_without_gpu_omits_resources(tmp_path: Path) -> None:
    project_dir = _create_project(tmp_path, entrypoint="python -m app.main")

    manifest_path = tmp_path / "job.yaml"
    cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        result = runner.invoke(
            app,
            [
                "job",
                str(project_dir),
                "--input-size",
                "512Mi",
                "--output",
                str(manifest_path),
            ],
            catch_exceptions=False,
        )
    finally:
        os.chdir(cwd)

    assert result.exit_code == 0
    assert "Job manifest written to" in result.stdout

    manifest_docs = list(yaml.safe_load_all(manifest_path.read_text()))
    assert len(manifest_docs) == 2
    manifest = manifest_docs[0]
    output_pvc_doc = manifest_docs[1]

    container = manifest["spec"]["template"]["spec"]["containers"][0]
    assert "resources" not in container
    assert "env" not in container
    assert "metadata" not in manifest["spec"]["template"]
    security_context = manifest["spec"]["template"]["spec"]["securityContext"]
    assert security_context["fsGroup"] == 1000

    volumes = {v["name"]: v for v in manifest["spec"]["template"]["spec"]["volumes"]}
    assert "input" not in volumes
    output_claim = volumes["output"]["persistentVolumeClaim"]["claimName"]

    output_mounts = {m["name"]: m for m in container["volumeMounts"]}
    assert "input" not in output_mounts

    assert output_pvc_doc["metadata"]["name"] == output_claim
    assert output_pvc_doc["spec"]["resources"]["requests"]["storage"] == "1Gi"
