# walkai CLI

walkai is an opinionated command-line tool that turns Python projects into container images the same way every time. It reads a project's `pyproject.toml`, prepares a build context, invokes the [pack](https://buildpacks.io/docs/tools/pack/) CLI to create an image, and can push that image to a configured registry.

## Prerequisites

- Python 3.13+
- [`uv`](https://docs.astral.sh/uv/) for dependency management and local installs
- [`pack`](https://buildpacks.io/docs/tools/pack/) CLI available on your `PATH`
- A container client (`docker` or `podman`) capable of tagging and pushing images

## Installing

```bash
uv tool install --editable .
```

This makes a `walkai` executable available in your environment, using the dependencies specified in `pyproject.toml`.

## Project Configuration

Every project you build must declare a `[tool.walkai]` section inside its `pyproject.toml`:

```toml
[tool.walkai]
entrypoint = "python -m app.main"
env_file = ".env.production"
os_dependencies = ["git", "gettext", "cron"]
```

- `entrypoint` (required) is the command that will run when the container starts. walkai writes this to a `Procfile` for the buildpacks to pick up.
- `env_file` (optional) points to a file containing environment variables to pass into `pack` via `--env-file`.
- `os_dependencies` (optional) is a list of Debian packages to install in the image. With the default Heroku builder walkai writes these into `project.toml`; when you swap to a Paketo builder walkai passes the same list to the APT buildpack via `BP_APT_PACKAGES`.

## Commands

### Configure registry credentials

```bash
walkai config --url registry.example.com --username my-user
# You will be prompted for the password if not supplied via --password.
```

The credentials are stored in `~/.config/walkai/config.toml` (permissions tightened on POSIX systems). Run `walkai config --show-path` to print the exact location.

### Build an image

```bash
walkai build path/to/project --image my-api:latest
```

- Uses Heroku's `heroku/builder:24` builder under the hood.
- Installs OS dependencies declared in `[tool.walkai].os_dependencies` by updating the Heroku `project.toml` descriptor (entries are written with `force = true` so binaries are always available).
- Provide a different env file with `--env-file` if your `pyproject.toml` specifies one you want to replace.

If `--image` is omitted, walkai falls back to `walkai/<project-name>:latest`.

### Push an image

```bash
walkai push my-api:latest
```

- Reads the saved registry credentials.
- Logs in with `docker` (default) or `podman` if you pass `--client podman`.
- Retags the local image to `<registry>/<image>` (or `<registry>/<repository>` if `--repository` is provided) and pushes it.

## Troubleshooting

- Ensure `pack`, `docker`/`podman`, and `uv` are installed and available on your `PATH`.
- `walkai build` copies your project into a temporary directory; rerun the command after making changes.
- If the build fails because the `pack` CLI is missing, install it from the [Buildpacks documentation](https://buildpacks.io/docs/tools/pack/).
