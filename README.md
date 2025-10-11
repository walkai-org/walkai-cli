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
os_dependencies = ["git", "gettext", "cron"]
inputs = ["datasets/sample.csv"]
gpu = "1g.10gb"
storage = 5
```

- `entrypoint` (required) is the command that will run when the container starts.
- `env_file` (optional) points to a dotenv-style file whose variables are injected into the generated Kubernetes job manifest.
- `os_dependencies` (optional) is a list of Debian packages to install in the image. The default Heroku builder synthesises a `project.toml` describing these dependencies so the deb-packages buildpack can install them.
- `inputs` (optional) is a list of files or directories that walkai should exclude from the container image and instead package into the generated input PersistentVolumeClaim before the job starts.
- `gpu` (optional) is a MIG profile string (for example `"1g.10gb"`). When present, walkai adds a `nvidia.com/mig-<profile>` resource limit with a value of `1`.
- `storage` (required) is the number of Gi requested when submitting jobs to the WalkAI API.

## Commands

### Configure registry credentials

```bash
walkai config --url registry.example.com --username my-user --api-url https://api.walkai.ai
# You will be prompted for the registry password and WalkAI PAT if not supplied via
# --password / --pat.
```

The credentials and WalkAI API settings are stored in `~/.config/walkai/config.toml`.

### Build an image

```bash
walkai build path/to/project --image my-api:latest
```


If `--image` is omitted, walkai falls back to `walkai/<project-name>:latest`.

### Push an image

```bash
walkai push my-api:latest
```

Reads the saved registry credentials.
You can use this command to push any container image, not just the ones built with the tool.

### Generate a Kubernetes job manifest

```bash
walkai job path/to/project \
  --image my-api:latest \
  --input-size 2Gi \
  --output-size 5Gi \
  --output job.yaml
```

- Generates a `batch/v1` Job and appends the output PersistentVolumeClaim to the same manifest. `/opt/output` is writable for results.
- Sets the pod `fsGroup` to ensure the job process can write to `/opt/output` when the volume is mounted.
- Sets `restartPolicy: Never` and `backoffLimit: 0` so jobs fail fast.
- Use `--input-size`/`--output-size` to control the PVC storage requests (defaults to `1Gi`).
- When `[tool.walkai].inputs` is set, the manifest includes the `/opt/input` volume, an input PVC manifest is written to `<job>-input-pvc.yaml` (override with `--pvc-output`), and a tarball of the declared paths is created (default `<job>-inputs.tgz`). Apply the input PVC manifest, mount the claim into a helper pod, and unpack the archive into `/opt/input` before launching the job.
- Requests MIG-backed GPUs when `[tool.walkai].gpu` is configured, and injects environment variables from `[tool.walkai].env_file` if present.
- Use `--output` to write the manifest to disk or omit it to stream YAML to STDOUT.

### Submit a job to WalkAI

```bash
walkai submit path/to/project --image my-api:latest
```

Reads the WalkAI API credentials stored via `walkai config` and posts the image, GPU profile, and storage request from `[tool.walkai]` to `<api-url>/jobs/`.
