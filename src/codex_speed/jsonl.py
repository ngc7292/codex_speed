"""Parsing helpers for Codex JSONL streams."""

from __future__ import annotations

import json
from typing import Any

from codex_speed.events import UsagePayload


def parse_json_line(line: bytes) -> dict[str, Any] | None:
    """Parse one JSONL line.

    Args:
        line: Raw line bytes, with or without a trailing newline.

    Returns:
        Parsed JSON object or ``None`` for blank/non-object lines.

    Raises:
        json.JSONDecodeError: If the line is non-empty invalid JSON.
    """

    stripped = line.strip()
    if not stripped:
        return None
    value = json.loads(stripped.decode("utf-8"))
    if isinstance(value, dict):
        return value
    return None


def extract_turn_usage(event: dict[str, Any]) -> UsagePayload | None:
    """Extract usage from a ``turn.completed`` JSONL event."""

    if event.get("type") != "turn.completed":
        return None
    usage = event.get("usage")
    if not isinstance(usage, dict):
        return None

    result: UsagePayload = {}
    for key in (
        "input_tokens",
        "cached_input_tokens",
        "output_tokens",
        "reasoning_output_tokens",
    ):
        value = usage.get(key)
        if isinstance(value, int) and value >= 0:
            result[key] = value
    return result

