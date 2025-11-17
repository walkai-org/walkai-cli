# walkai CLI

walkai is an opinionated command-line tool that turns Python projects into container images and interfaces with the walkai API.

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
ignore = ["datasets/sample.csv"]
```

- `entrypoint` (required) is the command that will run when the container starts.
- `os_dependencies` (optional) is a list of Debian packages to install in the image. The default Heroku builder synthesises a `project.toml` describing these dependencies so the deb-packages buildpack can install them.
- `ignore` (optional) is a list of files or directories that walkai should exclude from the container image (useful for large datasets you plan to mount separately).

## Commands

### Configure WalkAI API access

```bash
walkai config
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

Pushes an image to the walk:ai registry so the cluster can access the image.
You can use this command to push any container image, not just the ones built with the tool.

### Submit a job to WalkAI

```bash
walkai submit path/to/project --image my-api:latest --gpu 1g.10gb --storage 5
```

Reads the WalkAI API credentials stored via `walkai config`, posts the provided image, and forwards the `--gpu`/`--storage` values to the WalkAI API, submitting a new job. Add `--secret name` (repeatable) to include secrets with the submission. Add `--input <id>` to attach an input volume.

### Manage secrets

List the secrets currently stored in your WalkAI account:

```bash
walkai secrets list
```

Create or update a secret from a `.env` file or inline key/value pairs:

```bash
walkai secrets create prod-env --env-file .env
walkai secrets create prod-env --data API_KEY=abc123 --data REGION=us-west1
```

Show the keys stored in a secret:

```bash
walkai secrets get prod-env
```

Delete a secret (confirmation required unless `--yes` is provided):

```bash
walkai secrets delete prod-env
```

`walkai secrets list --json` prints the raw API payload, which is useful for scripting.

### Manage input volumes

List input volumes (id, name, size):

```bash
walkai input list
```

Create a new input volume and upload files:

```bash
walkai input create --size 5 --file path/to/file1 --file path/to/file2
```

List the objects stored in a specific input volume:

```bash
walkai input get 141
```

Add `--json` to either command to print the underlying API response instead of the formatted output.
