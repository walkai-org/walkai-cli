"""walkai CLI entry point implemented with Typer."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import httpx
import typer

from walkai.build import BuildError, build_image
from walkai.configuration import (
    ConfigError,
    WalkAIAPIConfig,
    WalkAIConfig,
    config_path,
    delete_config,
    load_config,
    save_config,
)
from walkai.project import ProjectConfigError, load_project_config
from walkai.push import PushError, fetch_registry_credentials, push_image
from walkai.secrets import (
    SecretsError,
    create_secret,
    delete_secret,
    get_secret,
    list_secrets,
    parse_env_file,
)

from . import __version__

app = typer.Typer(
    help="Opinionated tooling to build and push Python apps for Kubernetes."
)
secrets_app = typer.Typer(help="Manage WalkAI secrets.")
app.add_typer(secrets_app, name="secrets")


def _load_api_config() -> WalkAIAPIConfig:
    """Load the stored API configuration or exit with an error."""

    try:
        stored_config = load_config()
    except ConfigError as exc:
        typer.secho(str(exc), err=True, fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc

    if stored_config is None:
        typer.secho(
            "No WalkAI configuration found. Run 'walkai config' first.",
            err=True,
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)

    return stored_config.walkai_api


def _parse_inline_pairs(pairs: Sequence[str]) -> dict[str, str]:
    """Parse KEY=VALUE pairs passed via the CLI."""

    data: dict[str, str] = {}
    for raw in pairs:
        if "=" not in raw:
            raise SecretsError(
                f"Invalid --data value '{raw}'. Expected the format KEY=VALUE."
            )
        key, value = raw.split("=", 1)
        key = key.strip()
        if not key:
            raise SecretsError("Secret data keys cannot be empty.")
        data[key] = value

    return data


@secrets_app.command("list")
def secrets_list(
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Print the raw JSON payload from the API.",
    ),
) -> None:
    """List the available secrets."""

    walkai_api = _load_api_config()

    try:
        secrets = list_secrets(walkai_api)
    except SecretsError as exc:
        typer.secho(str(exc), err=True, fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc

    if json_output:
        typer.echo(json.dumps(secrets, indent=2))
        return

    if not secrets:
        typer.secho("No secrets found.", fg=typer.colors.YELLOW)
        return

    typer.secho("Secrets:", fg=typer.colors.CYAN)
    for entry in secrets:
        typer.echo(f"- {entry['name']}")


@secrets_app.command("get")
def secrets_get(
    name: str = typer.Argument(..., help="Name of the secret to retrieve."),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Print the raw JSON payload from the API.",
    ),
) -> None:
    """Fetch a single secret."""

    walkai_api = _load_api_config()

    try:
        secret = get_secret(walkai_api, name=name)
    except SecretsError as exc:
        typer.secho(str(exc), err=True, fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc

    if json_output:
        typer.echo(json.dumps(secret, indent=2))
        return

    typer.secho(f"Secret: {secret['name']}", fg=typer.colors.CYAN)
    keys = secret.get("keys") or []

    if not keys:
        typer.secho("No keys found for this secret.", fg=typer.colors.YELLOW)
        return

    typer.echo("Keys:")
    for key in keys:
        typer.echo(f"- {key}")


@secrets_app.command("create")
def secrets_create(
    name: str = typer.Argument(..., help="Name of the secret to create or update."),
    env_file: Path | None = typer.Option(
        None,
        "--env-file",
        "-f",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        resolve_path=True,
        help="Path to a .env formatted file whose values will populate the secret.",
    ),
    data_pairs: list[str] = typer.Option(
        [],
        "--data",
        "-d",
        help="Inline KEY=VALUE pair to include in the secret. Repeat for multiple pairs.",
        show_default=False,
    ),
) -> None:
    """Create a secret from CLI key/value pairs or a .env file."""

    walkai_api = _load_api_config()
    merged: dict[str, str] = {}

    if env_file is not None:
        try:
            file_data = parse_env_file(env_file)
        except SecretsError as exc:
            typer.secho(str(exc), err=True, fg=typer.colors.RED)
            raise typer.Exit(code=1) from exc
        merged.update(file_data)

    try:
        inline_data = _parse_inline_pairs(data_pairs)
    except SecretsError as exc:
        typer.secho(str(exc), err=True, fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc

    merged.update(inline_data)

    if not merged:
        typer.secho(
            "Secret data is empty. Provide --env-file or at least one --data option.",
            err=True,
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)

    try:
        create_secret(walkai_api, name=name, data=merged)
    except SecretsError as exc:
        typer.secho(str(exc), err=True, fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc

    typer.secho(f"Secret '{name}' saved.", fg=typer.colors.GREEN)


@secrets_app.command("delete")
def secrets_delete(
    name: str = typer.Argument(..., help="Name of the secret to delete."),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Skip the confirmation prompt.",
    ),
) -> None:
    """Delete a secret by name."""

    if not yes:
        confirmed = typer.confirm(
            f"Delete secret '{name}'? (y/n)", default=False, show_default=False
        )
        if not confirmed:
            typer.echo("Aborted.")
            raise typer.Exit()

    walkai_api = _load_api_config()

    try:
        delete_secret(walkai_api, name=name)
    except SecretsError as exc:
        typer.secho(str(exc), err=True, fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc

    typer.secho(f"Secret '{name}' deleted.", fg=typer.colors.GREEN)


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
        help="Delete the stored WalkAI configuration instead of updating it.",
    ),
) -> None:
    """Save or clear WalkAI API credentials used by the push/submit commands."""

    if clear:
        if any(value is not None for value in (api_url, pat)):
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
            typer.secho("WalkAI configuration deleted.", fg=typer.colors.GREEN)
        else:
            typer.secho(
                "No WalkAI configuration found to delete.",
                fg=typer.colors.YELLOW,
            )

        if show_path:
            typer.echo(f"Location: {config_path()}")

        return

    if api_url is None:
        api_url = typer.prompt("WalkAI API URL")
    if pat is None:
        pat = typer.prompt("WalkAI personal access token", hide_input=True)

    config_model = WalkAIConfig(
        walkai_api=WalkAIAPIConfig(url=api_url.strip(), pat=pat),  # type: ignore
    )
    saved_path = save_config(config_model)

    typer.secho("WalkAI configuration saved.", fg=typer.colors.GREEN)
    if show_path:
        typer.echo(f"Location: {saved_path}")


@app.command()
def push(
    image: str = typer.Argument(..., help="Local image reference to push."),
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
            "No WalkAI configuration found. Run 'walkai config' first.",
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

    walkai_api = stored_config.walkai_api

    try:
        credentials = fetch_registry_credentials(walkai_api)
        remote_ref = push_image(
            local_image=image,
            credentials=credentials,
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
    secrets: list[str] = typer.Option(
        [],
        "--secret",
        "-s",
        help="Secret name to include with the submission. Repeat the option for multiple secrets.",
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

    if cli_config is None:
        typer.secho(
            "No WalkAI API configuration found. Run 'walkai config' first.",
            err=True,
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)

    walkai_api = cli_config.walkai_api

    base_url = walkai_api.url.rstrip("/")
    endpoint = f"{base_url}/jobs/"

    resolved_image = image or project.default_image()
    payload = {
        "image": resolved_image,
        "gpu": project.gpu,
        "storage": project.storage,
    }
    if secrets:
        payload["secret_names"] = secrets

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
