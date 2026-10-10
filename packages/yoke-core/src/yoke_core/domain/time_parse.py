"""Strict UTC instant parsing and whole elapsed-age displays."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from yoke_contracts.timestamps import as_utc, parse_instant, utc_now


def parse_timestamp_utc(value: object) -> Optional[datetime]:
    """Normalize a supplied instant; only null represents absence."""
    return None if value is None else parse_instant(value)


def age_hours_since(value: object, *, now: Optional[datetime] = None) -> int:
    """Return whole non-negative elapsed hours; null has no known age."""
    parsed = parse_timestamp_utc(value)
    if parsed is None:
        return 0
    anchor = as_utc(now) if now is not None else utc_now()
    return max(0, (anchor - parsed) // timedelta(hours=1))


def age_minutes_since(value: object, *, now: Optional[datetime] = None) -> int:
    """Return whole non-negative elapsed minutes; null has no known age."""
    parsed = parse_timestamp_utc(value)
    if parsed is None:
        return 0
    anchor = as_utc(now) if now is not None else utc_now()
    return max(0, (anchor - parsed) // timedelta(minutes=1))


__all__ = ["age_hours_since", "age_minutes_since", "parse_timestamp_utc"]
