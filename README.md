# walkai CLI

walkai is an opinionated command-line tool that turns Python projects into container images.

## Prerequisites

- Python 3.13+
- [`uv`](https://docs.astral.sh/uv/)
- [`pack`](https://buildpacks.io/docs/tools/pack/)
- A container client (`docker` or `podman`)

## Installing

```bash
uv tool install git+https://github.com/saguirregaray1/walkai-cli
```


Or, you can install it like this for development:
```bash
uv tool install --editable .
```

## Project Configuration

Every project you build must declare a `[tool.walkai]` section inside its `pyproject.toml`:

```toml
[tool.walkai]
entrypoint = "python -m app.main"
env_file = ".env.production"
os_dependencies = ["git", "gettext", "cron"]
```

- `entrypoint` (required) is the command that will run when the container starts.
- `env_file` (optional) points to a file containing environment variables to pass into `pack` via `--env-file`.
- `os_dependencies` (optional) is a list of Debian packages to install in the image.

## Commands

### Configure registry credentials

```bash
walkai config --url registry.example.com --username my-user
# You will be prompted for the password if not supplied via --password.
```

The credentials are stored in `~/.config/walkai/config.toml`.

### Build an image

```bash
walkai build path/to/project --image my-api:latest
```


You can provide a different env file with `--env-file` if your `pyproject.toml` specifies one you want to replace.

If `--image` is omitted, walkai falls back to `walkai/<project-name>:latest`.

### Push an image

```bash
walkai push my-api:latest
```

Reads the saved registry credentials.
You can use this command to push any container image, not just the ones built with the tool.

