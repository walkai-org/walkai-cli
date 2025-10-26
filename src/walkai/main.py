"""walkai CLI entry point implemented with Typer."""

from pathlib import Path

import httpx
import typer

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
from walkai.project import ProjectConfigError, load_project_config
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
        if any(value is not None for value in (url, username, password, api_url, pat)):
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
def submit(
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
        help="Container image to submit. Defaults to walkai/<project>:latest.",
    ),
) -> None:
    """Submit a job to the WalkAI API."""

    try:
        project = load_project_config(path)
    except ProjectConfigError as exc:
        typer.secho(str(exc), err=True, fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc

    if project.gpu is None:
        typer.secho(
            "Project configuration must define [tool.walkai].gpu to submit a job.",
            err=True,
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)

    try:
        cli_config = load_config()
    except ConfigError as exc:
        typer.secho(str(exc), err=True, fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc

    if cli_config is None or cli_config.walkai_api is None:
        typer.secho(
            "No WalkAI API configuration found. Run 'walkai config' first.",
            err=True,
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)

    walkai_api = cli_config.walkai_api
    assert walkai_api is not None  # narrow type for mypy

    base_url = walkai_api.url.rstrip("/")
    endpoint = f"{base_url}/jobs/"

    resolved_image = image or project.default_image()
    payload = {
        "image": resolved_image,
        "gpu": project.gpu,
        "storage": project.storage,
    }

    headers = {
        "Authorization": f"Bearer {walkai_api.pat}",
    }

    try:
        response = httpx.post(endpoint, json=payload, headers=headers, timeout=30)
    except httpx.RequestError as exc:
        typer.secho(f"Failed to reach WalkAI API: {exc}", err=True, fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc

    if response.status_code >= 400:
        detail = response.text.strip() or f"HTTP {response.status_code}"
        typer.secho(f"Job submission failed: {detail}", err=True, fg=typer.colors.RED)
        raise typer.Exit(code=1)

    job_reference: str | None = None
    try:
        data = response.json()
    except ValueError:
        typer.secho("Job submission didn't emit a response", fg=typer.colors.YELLOW)
    job_reference = data.get("job_id")
    pod_reference = data.get("pod")

    message = "Job submitted successfully."
    if job_reference:
        message = f"Job submitted successfully with ID: {job_reference} and pod {pod_reference}"

    typer.secho(message, fg=typer.colors.GREEN)


if __name__ == "__main__":
    app()
