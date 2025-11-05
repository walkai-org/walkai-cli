# walkai CLI

walkai is an opinionated command-line tool that turns Python projects into container images.

## Prerequisites

- Python 3.13+
- [`uv`](https://docs.astral.sh/uv/)
- [`pack`](https://buildpacks.io/docs/tools/pack/)
- A container client (`docker` or `podman`)

## Installing

```bash
uv tool install git+https://github.com/walkai-org/walkai-cli
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
os_dependencies = ["git", "gettext", "cron"]
inputs = ["datasets/sample.csv"]
gpu = "1g.10gb"
storage = 5
```

- `entrypoint` (required) is the command that will run when the container starts.
- `os_dependencies` (optional) is a list of Debian packages to install in the image. The default Heroku builder synthesises a `project.toml` describing these dependencies so the deb-packages buildpack can install them.
- `inputs` (optional) is a list of files or directories that walkai should exclude from the container image (useful for large datasets you plan to mount separately).
- `gpu` (required) is a MIG profile string (for example `"1g.10gb"`). walkai validates that the field is present and forwards it to the WalkAI API when submitting jobs.
- `storage` (required) is the number of Gi requested when submitting jobs to the WalkAI API.

## Commands

### Configure WalkAI API access

```bash
walkai config --api-url https://api.walkai.ai
# You will be prompted for the WalkAI PAT if it is not supplied via --pat.
```

The WalkAI API settings are stored in `~/.config/walkai/config.toml`.

### Build an image

```bash
walkai build path/to/project --image my-api:latest
```


If `--image` is omitted, walkai falls back to `walkai/<project-name>:latest`.

### Push an image

```bash
walkai push my-api:latest
```

Retrieves short-lived registry credentials from the WalkAI API (`GET /registry`) using the saved PAT before pushing.
You can use this command to push any container image, not just the ones built with the tool.

### Submit a job to WalkAI

```bash
walkai submit path/to/project --image my-api:latest
```

Reads the WalkAI API credentials stored via `walkai config` and posts the image, GPU profile, and storage request from `[tool.walkai]` to `<api-url>/jobs/`.
