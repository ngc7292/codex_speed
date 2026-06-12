"""Loopback HTTP daemon exposing Prometheus metrics."""

from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from codex_speed.metrics import MetricsRegistry

ALLOWED_BIND_HOSTS = {"127.0.0.1", "localhost", "::1", "0.0.0.0"}


class MetricsHTTPServer(ThreadingHTTPServer):
    """HTTP server carrying a metrics registry."""

    def __init__(self, server_address: tuple[str, int], registry: MetricsRegistry) -> None:
        super().__init__(server_address, MetricsHandler)
        self.registry = registry


class MetricsHandler(BaseHTTPRequestHandler):
    """HTTP request handler for daemon endpoints."""

    server: MetricsHTTPServer

    def log_message(self, format: str, *args: Any) -> None:
        """Silence default access logging."""

    def do_GET(self) -> None:
        """Handle health and Prometheus scrape requests."""

        if self.path == "/healthz":
            self._send_bytes(HTTPStatus.OK, b"ok\n", "text/plain; charset=utf-8")
            return
        if self.path == "/metrics":
            body = self.server.registry.render().encode("utf-8")
            self._send_bytes(HTTPStatus.OK, body, "text/plain; version=0.0.4; charset=utf-8")
            return
        self._send_bytes(HTTPStatus.NOT_FOUND, b"not found\n", "text/plain; charset=utf-8")

    def do_POST(self) -> None:
        """Handle collector event ingestion."""

        if self.path != "/v1/events":
            self._send_bytes(HTTPStatus.NOT_FOUND, b"not found\n", "text/plain; charset=utf-8")
            return
        length_header = self.headers.get("Content-Length")
        try:
            length = int(length_header or "0")
        except ValueError:
            self._send_bytes(HTTPStatus.BAD_REQUEST, b"invalid content length\n", "text/plain")
            return
        if length <= 0 or length > 1_000_000:
            self._send_bytes(HTTPStatus.BAD_REQUEST, b"invalid event size\n", "text/plain")
            return
        raw_body = self.rfile.read(length)
        try:
            event = json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError:
            self._send_bytes(HTTPStatus.BAD_REQUEST, b"invalid json\n", "text/plain")
            return
        if not isinstance(event, dict):
            self._send_bytes(HTTPStatus.BAD_REQUEST, b"event must be an object\n", "text/plain")
            return
        self.server.registry.apply_event(event)
        self._send_bytes(HTTPStatus.ACCEPTED, b"accepted\n", "text/plain; charset=utf-8")

    def _send_bytes(self, status: HTTPStatus, body: bytes, content_type: str) -> None:
        self.send_response(int(status))
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def run_daemon(host: str, port: int) -> None:
    """Run the metrics daemon until interrupted."""

    if host not in ALLOWED_BIND_HOSTS:
        raise ValueError("codex-speed daemon must bind to a loopback address or 0.0.0.0")
    registry = MetricsRegistry()
    server = MetricsHTTPServer((host, port), registry)
    print(f"codex-speed daemon listening on http://{host}:{server.server_port}")
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        print("codex-speed daemon shutting down")
    finally:
        server.server_close()
