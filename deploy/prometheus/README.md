# codex-speed Prometheus and Grafana

This directory contains the Docker Compose deployment for the local monitoring
stack. Prefer running it through the root `Makefile`.

Images are pinned for Prometheus and Grafana:

- `prom/prometheus:v2.55.1`
- `grafana/grafana:12.0.2`

The `codex-speed` daemon image is built locally from the repo root. No secrets
are required. All published ports are bound to `127.0.0.1`.

## Start

From the repo root:

```bash
make deploy
```

Equivalent direct command:

```bash
docker compose -f deploy/prometheus/docker-compose.yml up -d --build
```

Published endpoints:

```text
codex-speed: http://127.0.0.1:9467
Prometheus:  http://127.0.0.1:9090
Grafana:     http://127.0.0.1:3000
```

## Verify

From the repo root:

```bash
make verify
```

This checks:

- daemon `/healthz`
- Prometheus `/-/ready`
- Grafana `/api/health`
- Prometheus query `up{job="codex-speed"}` returns `1`

Open the dashboard:

```text
http://127.0.0.1:3000/d/codex-speed/codex-speed
```

## Stop

```bash
make stop
```

Equivalent direct command:

```bash
docker compose -f deploy/prometheus/docker-compose.yml down
```

## Rollback

Rollback removes the containers and local monitoring volumes:

```bash
make rollback
```

Equivalent direct command:

```bash
docker compose -f deploy/prometheus/docker-compose.yml down -v --remove-orphans
```

## Troubleshooting

Check rendered Compose configuration:

```bash
make compose-config
```

Follow logs:

```bash
make logs
```

Check daemon metrics directly:

```bash
python3 -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:9467/metrics').read().decode())"
```
