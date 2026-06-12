"""Utilities for terminal text normalization."""

from __future__ import annotations

import re

ANSI_RE = re.compile(
    r"""
    \x1B
    (?:
      \[[0-?]*[ -/]*[@-~]
      |\][^\x07]*(?:\x07|\x1B\\)
      |[PX^_].*?\x1B\\
      |[@-_]
    )
    """,
    re.VERBOSE | re.DOTALL,
)


def strip_ansi(text: str) -> str:
    """Return *text* with ANSI control sequences removed."""

    return ANSI_RE.sub("", text)


def visible_byte_count(data: bytes) -> int:
    """Count UTF-8 bytes after best-effort ANSI stripping.

    Args:
        data: Raw terminal bytes.

    Returns:
        Number of bytes in the visible text representation.
    """

    text = data.decode("utf-8", errors="ignore")
    return len(strip_ansi(text).encode("utf-8"))

