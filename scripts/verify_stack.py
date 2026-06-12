"""Verify the local Docker Compose deployment."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any


def main() -> None:
    """Run deployment health checks."""

    wait_for("codex-speed daemon", check_daemon)
    wait_for("Prometheus readiness", check_prometheus_ready)
    wait_for("Grafana health", check_grafana_health)
    wait_for("Prometheus codex-speed scrape", check_prometheus_scrape)


def wait_for(
    name: str,
    check: Callable[[], str],
    *,
    timeout_seconds: float = 60.0,
    interval_seconds: float = 1.0,
) -> None:
    """Wait for one deployment check to pass."""

    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            detail = check()
        except (AssertionError, OSError, urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
            time.sleep(interval_seconds)
            continue
        print(f"ok: {name}: {detail}")
        return
    raise SystemExit(f"failed: {name}: {last_error}")


def check_daemon() -> str:
    """Check the codex-speed daemon health endpoint."""

    body = read_text("http://127.0.0.1:9467/healthz").strip()
    assert body == "ok", body
    return body


def check_prometheus_ready() -> str:
    """Check the Prometheus readiness endpoint."""

    body = read_text("http://127.0.0.1:9090/-/ready").strip()
    assert body, "empty readiness response"
    return body.splitlines()[0]


def check_grafana_health() -> str:
    """Check the Grafana health endpoint."""

    payload = read_json("http://127.0.0.1:3000/api/health")
    assert payload.get("database") == "ok", payload
    return f"database={payload['database']}"


def check_prometheus_scrape() -> str:
    """Check that Prometheus sees the codex-speed target as up."""

    query = urllib.parse.quote('up{job="codex-speed"}')
    payload = read_json(f"http://127.0.0.1:9090/api/v1/query?query={query}")
    assert payload.get("status") == "success", payload
    results = payload["data"]["result"]
    assert results, payload
    for result in results:
        value = result.get("value", [])
        if len(value) == 2 and value[1] == "1":
            return "up=1"
    raise AssertionError(payload)


def read_text(url: str) -> str:
    """Read a URL as UTF-8 text."""

    with urllib.request.urlopen(url, timeout=5) as response:
        return response.read().decode("utf-8")


def read_json(url: str) -> dict[str, Any]:
    """Read a URL as a JSON object."""

    payload = json.loads(read_text(url))
    assert isinstance(payload, dict), payload
    return payload


if __name__ == "__main__":
    main()
