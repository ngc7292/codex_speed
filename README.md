# codex-speed

`codex-speed` monitors local Codex CLI input and output speed and exposes
Prometheus metrics from a local daemon.

The Docker Compose deployment is the default path for this repo. It starts:

- `codex-speed` daemon at `http://127.0.0.1:9467`
- Prometheus at `http://127.0.0.1:9090`
- Grafana at `http://127.0.0.1:3000`

The daemon stores metrics and metadata only. It does not persist prompt or
response text and does not read `~/.codex/auth.json`.

## Quick Deploy

Prerequisites:

- Docker Desktop or Docker Engine with the Compose plugin
- Python 3.11+ for local test and verification commands

From the repo root:

```bash
make test
make smoke
make compose-config
make deploy
make verify
```

Open the provisioned Grafana dashboard:

```text
http://127.0.0.1:3000/d/codex-speed/codex-speed
```

Stop the stack:

```bash
make stop
```

Remove containers and local Prometheus/Grafana volumes:

```bash
make rollback
```

## Track Host Codex Invocations

The Docker stack only runs the metrics daemon and dashboards. To track normal
host-side `codex ...` commands, install the PATH shim explicitly:

```bash
make install-shim
```

Put this near the top of your shell config so it appears before the real Codex
directory:

```bash
export PATH="$HOME/.codex-speed/bin:$PATH"
```

Restart the shell or run:

```bash
hash -r
command -v codex
```

`command -v codex` should print `$HOME/.codex-speed/bin/codex`. After that,
use Codex normally:

```bash
codex
codex --no-alt-screen
codex exec "say hi"
codex review
```

The shim sends events to `http://127.0.0.1:9467`, which is published by the
Docker Compose stack. To bypass tracking for one command:

```bash
CODEX_SPEED_DISABLE=1 codex ...
```

Remove the shim:

```bash
make uninstall-shim
```

## Local Development

Install the package in editable mode:

```bash
make install-dev
```

Run the daemon without Docker:

```bash
PYTHONPATH=src python3 -m codex_speed daemon --listen 127.0.0.1:9467
```

In another terminal:

```bash
PYTHONPATH=src python3 -m codex_speed exec -- "say hi"
python3 -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:9467/metrics').read().decode())"
```

Interactive mode:

```bash
PYTHONPATH=src python3 -m codex_speed tui -- --no-alt-screen
```

After installing the package, use `codex-speed` instead of
`python3 -m codex_speed`.

## Make Targets

```text
make install-dev     Install the Python package in editable mode
make test            Run the unit test suite
make smoke           Check the local CLI entry point
make compose-config  Validate Docker Compose configuration
make deploy          Build and start daemon, Prometheus, and Grafana
make verify          Check daemon, Prometheus, Grafana, and scrape status
make logs            Follow Docker Compose logs
make stop            Stop the Docker Compose stack
make rollback        Stop the stack and remove local data volumes
make install-shim    Install the host Codex PATH shim explicitly
make uninstall-shim  Remove the host Codex PATH shim
```

## Prometheus Queries

```promql
rate(codex_speed_io_bytes_total{mode="tui",direction="output"}[30s])
rate(codex_speed_estimated_tokens_total{mode="tui",direction="output"}[30s])
rate(codex_speed_usage_tokens_total{mode="exec",kind="output"}[5m])
sum(codex_speed_estimated_tokens_total{direction="output",accuracy="estimated"})
sum(codex_speed_usage_tokens_total{kind="output",accuracy="exact"})
avg(codex_speed_session_output_tokens_per_second{accuracy="estimated"})
avg(codex_speed_session_output_tokens_per_second{accuracy="exact"})
```

`codex_speed_session_output_tokens_per_second` is rendered only for active
sessions. It reports average output tokens per second from `session_start` to
the current scrape time, with `estimated` and `exact` accuracy labels kept
separate.

## Deployment Runbook

Docker Compose files, Grafana provisioning, and the stack runbook live in
[`deploy/prometheus/`](deploy/prometheus/README.md).
