"""Small local token estimator.

This intentionally avoids model-specific tokenizers so the runtime remains
dependency-free. Values are labelled ``accuracy="estimated"`` in metrics.
"""

from __future__ import annotations


def estimate_tokens_from_bytes(byte_count: int) -> int:
    """Estimate tokens from UTF-8 bytes using a conservative 4 bytes/token ratio."""

    if byte_count <= 0:
        return 0
    return max(1, (byte_count + 3) // 4)

