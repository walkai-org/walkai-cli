"""walkai CLI entry point implemented with Typer."""

import re
import tarfile
from pathlib import Path

import typer
import yaml

from walkai.build import BuildError, build_image
from walkai.configuration import (
    ConfigError,
    RegistryConfig,
    WalkAIAPIConfig,
    WalkAIConfig,
    config_path,
    delete_config,
    load_config,
    save_config,
)
from walkai.project import ProjectConfigError, WalkAIProjectConfig, load_project_config
from walkai.push import PushError, push_image

from . import __version__

app = typer.Typer(
    help="Opinionated tooling to build and push Python apps for Kubernetes."
)


@app.command()
def version() -> None:
    """Print the version"""
    typer.echo(__version__)
    raise typer.Exit()


@app.command()
def build(
    path: Path = typer.Argument(
        Path("."),
        exists=True,
        file_okay=False,
        readable=True,
        resolve_path=True,
        help="Project directory containing a pyproject.toml with tool.walkai settings.",
    ),
    image: str | None = typer.Option(
        None,
        "--image",
        "-i",
        help="Name of the image to build. Defaults to walkai/<project>:latest.",
    ),
) -> None:
    """Build a container image from"""

    try:
        built_image = build_image(
            project_dir=path,
            image=image,
        )
    except BuildError as exc:
        typer.secho(str(exc), err=True, fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc

    typer.secho(f"Image built successfully: {built_image}", fg=typer.colors.GREEN)


@app.command()
def config(
    url: str | None = typer.Option(
        None, "--url", help="Registry URL, e.g. registry.example.com"
    ),
    username: str | None = typer.Option(
        None, "--username", "-u", help="Registry username"
    ),
    password: str | None = typer.Option(
        None, "--password", "-p", help="Registry password"
    ),
    api_url: str | None = typer.Option(
        None,
        "--api-url",
        help="WalkAI API URL, e.g. https://api.walkai.ai",
    ),
    pat: str | None = typer.Option(
        None,
        "--pat",
        help="WalkAI personal access token",
    ),
    show_path: bool = typer.Option(
        False, "--show-path", help="Print the configuration file location."
    ),
    clear: bool = typer.Option(
        False,
        "--clear",
        help="Delete the stored registry configuration instead of updating it.",
    ),
) -> None:
    """Save or clear registry credentials used by the push command."""

    if clear:
        if any(
            value is not None
            for value in (url, username, password, api_url, pat)
        ):
            typer.secho(
                "Cannot combine credential options with --clear.",
                err=True,
                fg=typer.colors.RED,
            )
            raise typer.Exit(code=1)

        try:
            removed = delete_config()
        except ConfigError as exc:  # pragma: no cover - defensive guard
            typer.secho(str(exc), err=True, fg=typer.colors.RED)
            raise typer.Exit(code=1) from exc

        if removed:
            typer.secho("Registry configuration deleted.", fg=typer.colors.GREEN)
        else:
            typer.secho(
                "No registry configuration found to delete.",
                fg=typer.colors.YELLOW,
            )

        if show_path:
            typer.echo(f"Location: {config_path()}")

        return

    if url is None:
        url = typer.prompt("Registry URL")
    if username is None:
        username = typer.prompt("Registry username")
    if password is None:
        password = typer.prompt("Registry password", hide_input=True)
    if api_url is None:
        api_url = typer.prompt("WalkAI API URL")
    if pat is None:
        pat = typer.prompt("WalkAI personal access token", hide_input=True)

    config_model = WalkAIConfig(
        registry=RegistryConfig(
            url=url.strip(), username=username.strip(), password=password
        ),
        walkai_api=WalkAIAPIConfig(url=api_url.strip(), pat=pat),
    )
    saved_path = save_config(config_model)

    typer.secho("Registry configuration saved.", fg=typer.colors.GREEN)
    if show_path:
        typer.echo(f"Location: {saved_path}")


def _sanitise_name(value: str, fallback: str) -> str:
    candidate = re.sub(r"[^a-z0-9.-]+", "-", value.lower()).strip("-")
    if not candidate:
        return fallback
    return candidate[:63]

def _render_job_manifest(
    config: WalkAIProjectConfig,
    *,
    image: str,
    job_name: str,
    input_claim: str | None,
    output_claim: str,
) -> dict[str, object]:
    volume_mounts: list[dict[str, object]] = [
        {"name": "output", "mountPath": "/opt/output"}
    ]
    if input_claim:
        volume_mounts.insert(
            0,
            {
                "name": "input",
                "mountPath": "/opt/input",
                "readOnly": True,
            },
        )

    container: dict[str, object] = {
        "name": job_name,
        "image": image,
        "volumeMounts": volume_mounts,
    }

    if config.gpu:

        resource_key = f"nvidia.com/mig-{config.gpu}"
        container["resources"] = {"limits": {resource_key: 1}}

    if config.env_file:
        env_entries: list[dict[str, str]] = []
        for line in config.env_file.read_text().splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            key = key.strip()
            if not key:
                continue
            env_entries.append({"name": key, "value": value.strip()})
        if env_entries:
            container["env"] = env_entries

    volumes: list[dict[str, object]] = [
        {"name": "output", "persistentVolumeClaim": {"claimName": output_claim}}
    ]
    if input_claim:
        volumes.insert(
            0,
            {
                "name": "input",
                "persistentVolumeClaim": {"claimName": input_claim},
            },
        )

    pod_security_context: dict[str, object] = {
        # Cloud Native Buildpack images run processes as an unprivileged user. Ensure
        # the attached PVC is writable by aligning the pod's fsGroup with that user.
        "fsGroup": 1000,
    }

    template: dict[str, object] = {
        "spec": {
            "restartPolicy": "Never",
            "containers": [container],
            "volumes": volumes,
            "securityContext": pod_security_context,
        }
    }

    manifest: dict[str, object] = {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {"name": job_name},
        "spec": {"backoffLimit": 0, "template": template},
    }

    return manifest


def _render_persistent_volume_claim(
    *, name: str, storage: str, read_only: bool = False
) -> dict[str, object]:
    access_mode = "ReadWriteOnce"
    return {
        "apiVersion": "v1",
        "kind": "PersistentVolumeClaim",
        "metadata": {"name": name},
        "spec": {
            "accessModes": [access_mode],
            "resources": {"requests": {"storage": storage}},
        },
    }


@app.command()
def push(
    image: str = typer.Argument(..., help="Local image reference to push."),
    repository: str | None = typer.Option(
        None,
        "--repository",
        "-r",
        help="Override the remote repository path (defaults to <registry>/<image>).",
    ),
    client: str = typer.Option(
        "docker",
        "--client",
        help="Container client to use (docker or podman).",
        case_sensitive=False,
    ),
) -> None:
    """Push an image to the configured container registry."""

    try:
        stored_config = load_config()
    except ConfigError as exc:
        typer.secho(str(exc), err=True, fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc

    if stored_config is None:
        typer.secho(
            "No registry configuration found. Run 'walkai config' first.",
            err=True,
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)

    normalised_client = client.lower().strip()
    if normalised_client not in {"docker", "podman"}:
        typer.secho(
            "Client must be either 'docker' or 'podman'.", err=True, fg=typer.colors.RED
        )
        raise typer.Exit(code=1)

    try:
        remote_ref = push_image(
            local_image=image,
            config=stored_config.registry,
            repository=repository,
            client=normalised_client,  # type: ignore[arg-type]
        )
    except PushError as exc:
        typer.secho(str(exc), err=True, fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc

    typer.secho(f"Image pushed to {remote_ref}", fg=typer.colors.GREEN)


@app.command()
def job(
    path: Path = typer.Argument(
        Path("."),
        exists=True,
        file_okay=False,
        readable=True,
        resolve_path=True,
        help="Project directory containing a pyproject.toml with tool.walkai settings.",
    ),
    image: str | None = typer.Option(
        None,
        "--image",
        "-i",
        help="Container image to execute (defaults to walkai/<project>:latest).",
    ),
    input_size: str = typer.Option(
        "1Gi",
        "--input-size",
        help="Storage requested for the input PersistentVolumeClaim.",
    ),
    output_size: str = typer.Option(
        "1Gi",
        "--output-size",
        help="Storage requested for the output PersistentVolumeClaim.",
    ),
    pvc_output: Path | None = typer.Option(
        None,
        "--pvc-output",
        help="Path to write the input PVC manifest (defaults to <job>-input-pvc.yaml).",
    ),
    archive_output: Path | None = typer.Option(
        None,
        "--inputs-archive",
        help="Path to write a tarball containing declared inputs (defaults to <job>-inputs.tgz).",
    ),
    name: str | None = typer.Option(
        None,
        "--name",
        "-n",
        help="Override the generated job name.",
    ),
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Path to write the manifest to (defaults to STDOUT).",
    ),
) -> None:
    """Emit a Kubernetes Job manifest for the project."""

    try:
        config = load_project_config(path)
    except ProjectConfigError as exc:
        typer.secho(str(exc), err=True, fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc

    resolved_image = image or config.default_image()
    job_name = _sanitise_name(
        name or f"{config.project_name}-job", fallback="walkai-job"
    )
    has_inputs = bool(config.inputs)
    input_claim_name = (
        _sanitise_name(f"{job_name}-input", fallback="walkai-input")
        if has_inputs
        else None
    )
    output_claim_name = _sanitise_name(f"{job_name}-output", fallback="walkai-output")

    manifest = _render_job_manifest(
        config,
        image=resolved_image,
        job_name=job_name,
        input_claim=input_claim_name,
        output_claim=output_claim_name,
    )

    output_pvc_manifest = _render_persistent_volume_claim(
        name=output_claim_name, storage=output_size
    )

    if has_inputs and input_claim_name is not None:
        input_pvc_manifest = _render_persistent_volume_claim(
            name=input_claim_name, storage=input_size
        )
        input_pvc_path = pvc_output or Path(f"{job_name}-input-pvc.yaml")
        input_pvc_yaml = yaml.safe_dump(input_pvc_manifest, sort_keys=False)
        input_pvc_path.write_text(input_pvc_yaml)
        typer.secho(
            f"Input PVC manifest written to {input_pvc_path}",
            fg=typer.colors.GREEN,
        )

    if has_inputs:
        archive_path = archive_output or Path(f"{job_name}-inputs.tgz")
        with tarfile.open(archive_path, "w:gz") as archive:
            for input_path in config.inputs:
                try:
                    arcname = input_path.relative_to(config.root)
                except ValueError:
                    arcname = Path(input_path.name)
                archive.add(input_path, arcname=str(arcname))
        typer.secho(f"Inputs archive written to {archive_path}", fg=typer.colors.GREEN)
        typer.echo(
            "Apply the input PVC manifest, attach the claim to a helper pod, and "
            "copy the archive contents into /opt/input before starting the job."
        )

    job_documents = [manifest, output_pvc_manifest]
    job_yaml = yaml.safe_dump_all(job_documents, sort_keys=False)

    if output is not None:
        output.write_text(job_yaml)
        typer.secho(f"Job manifest written to {output}", fg=typer.colors.GREEN)
    else:
        typer.echo(job_yaml)


if __name__ == "__main__":
    app()
