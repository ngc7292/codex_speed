# Agent Guide

This repo contains `codex-speed`, a small Python CLI plus a local Docker
Compose deployment for monitoring Codex CLI input and output speed.

## Default Commands

Use these commands from the repo root:

```bash
make test
make smoke
make compose-config
make deploy
make verify
```

`make deploy` builds and starts the full local stack:

- `codex-speed` daemon on `127.0.0.1:9467`
- Prometheus on `127.0.0.1:9090`
- Grafana on `127.0.0.1:3000`

Stop the stack with:

```bash
make stop
```

Remove containers and local monitoring volumes with:

```bash
make rollback
```

## Constraints

- Do not expose ports on non-loopback interfaces unless explicitly requested.
- Do not run `make install-shim` unless the user explicitly wants the host
  `codex` PATH shim installed.
- Do not store prompts, responses, auth tokens, or Codex credentials in this
  repo or in Compose configuration.
- Prefer the Makefile targets over ad hoc shell commands so future agents can
  reproduce the same deployment path.

## Notes

The Dockerized daemon listens on `0.0.0.0:9467` inside the container, but Compose
publishes it only to `127.0.0.1:9467` on the host. Host-side wrappers should
continue sending events to the loopback default.
