"""Event shapes shared by collectors and the daemon."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, TypedDict

Mode = Literal["exec", "tui"]
Direction = Literal["input", "output"]
Stream = Literal["stdin", "stdout", "stderr", "pty"]


class UsagePayload(TypedDict, total=False):
    """Codex token usage fields emitted by ``turn.completed``."""

    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    reasoning_output_tokens: int


@dataclass(frozen=True)
class DaemonAddress:
    """HTTP daemon address."""

    host: str
    port: int

    @property
    def base_url(self) -> str:
        """Return the daemon base URL."""

        return f"http://{self.host}:{self.port}"


JsonObject = dict[str, Any]

