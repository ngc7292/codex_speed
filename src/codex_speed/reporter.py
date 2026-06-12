"""HTTP event reporter used by wrappers."""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from codex_speed.events import DaemonAddress


@dataclass
class EventReporter:
    """Best-effort local event reporter.

    Reporting failures never interrupt the wrapped Codex process. The first
    failure is printed to stderr; subsequent failures are silent.
    """

    address: DaemonAddress
    timeout_seconds: float = 0.25
    warn_once: bool = True

    def __post_init__(self) -> None:
        self._warned = False

    def send(self, event: dict[str, Any]) -> None:
        """Send one event to the daemon if it is reachable."""

        body = json.dumps(event, separators=(",", ":")).encode("utf-8")
        req = urllib.request.Request(
            f"{self.address.base_url}/v1/events",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as response:
                response.read()
        except (OSError, urllib.error.URLError) as exc:
            if self.warn_once and not self._warned:
                print(
                    f"codex-speed: daemon unavailable at {self.address.base_url}; "
                    f"metrics disabled for this run ({exc})",
                    file=sys.stderr,
                )
                self._warned = True

