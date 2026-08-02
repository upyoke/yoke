"""Validation shared by canonical item cancellation surfaces."""

from __future__ import annotations

from typing import Optional


def normalize_cancellation_reason(reason: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """Return a trimmed one-line cancellation reason or an error message."""
    normalized = (reason or "").strip()
    if not normalized:
        return None, "Cancelling an item requires a non-empty one-line reason."
    if "\n" in normalized or "\r" in normalized:
        return None, "Cancellation reason must be a single line."
    return normalized, None


__all__ = ["normalize_cancellation_reason"]
