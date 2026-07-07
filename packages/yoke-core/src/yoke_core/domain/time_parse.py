"""Timestamp parsing and age display helpers for Yoke ISO strings."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional


def parse_timestamp_utc(value: object) -> Optional[datetime]:
    """Parse a Yoke timestamp as UTC, returning ``None`` on bad input."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def age_hours_since(value: object, *, now: Optional[datetime] = None) -> int:
    """Return whole non-negative hours elapsed since ``value``."""
    parsed = parse_timestamp_utc(value)
    if parsed is None:
        return 0
    anchor = now or datetime.now(timezone.utc)
    if anchor.tzinfo is None:
        anchor = anchor.replace(tzinfo=timezone.utc)
    seconds = (anchor.astimezone(timezone.utc) - parsed).total_seconds()
    return max(0, int(seconds // 3600))


def age_minutes_since(value: object, *, now: Optional[datetime] = None) -> int:
    """Return whole non-negative minutes elapsed since ``value``."""
    parsed = parse_timestamp_utc(value)
    if parsed is None:
        return 0
    anchor = now or datetime.now(timezone.utc)
    if anchor.tzinfo is None:
        anchor = anchor.replace(tzinfo=timezone.utc)
    seconds = (anchor.astimezone(timezone.utc) - parsed).total_seconds()
    return max(0, int(seconds // 60))


__all__ = ["age_hours_since", "age_minutes_since", "parse_timestamp_utc"]
