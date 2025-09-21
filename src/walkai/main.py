"""walkai CLI entry point implemented with Typer."""

from pathlib import Path

import typer

from walkai.build import BuildError, build_image
from walkai.configuration import (
    ConfigError,
    RegistryConfig,
    load_config,
    save_config,
)
from walkai.push import PushError, push_image

from . import __version__

app = typer.Typer(
    help="Opinionated tooling to build and push Python apps for Kubernetes."
)


@app.callback()
def cli_root(
    _: typer.Context,
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        help="Show the walkai version and exit.",
    ),
) -> None:
    """Handle global options before any command runs."""

    if version:
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
    env_file: Path | None = typer.Option(
        None,
        "--env-file",
        exists=True,
        file_okay=True,
        dir_okay=False,
        resolve_path=True,
        help="Override the env file declared in tool.walkai.",
    ),
) -> None:
    """Build a container image using the pack CLI."""

    try:
        built_image = build_image(
            project_dir=path,
            image=image,
            env_file_override=env_file,
        )
    except BuildError as exc:
        typer.secho(str(exc), err=True, fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc

    typer.secho(f"Image built successfully: {built_image}", fg=typer.colors.GREEN)


@app.command()
def config(
    url: str = typer.Option(
        ..., "--url", help="Registry URL, e.g. registry.example.com"
    ),
    username: str = typer.Option(..., "--username", "-u", help="Registry username"),
    password: str = typer.Option(..., "--password", "-p", help="Registry password"),
    show_path: bool = typer.Option(
        False, "--show-path", help="Print the configuration file location."
    ),
) -> None:
    """Save registry credentials used by the push command."""
    config_model = RegistryConfig(
        url=url.strip(), username=username.strip(), password=password
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
            config=stored_config,
            repository=repository,
            client=normalised_client,  # type: ignore[arg-type]
        )
    except PushError as exc:
        typer.secho(str(exc), err=True, fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc

    typer.secho(f"Image pushed to {remote_ref}", fg=typer.colors.GREEN)


if __name__ == "__main__":
    app()
