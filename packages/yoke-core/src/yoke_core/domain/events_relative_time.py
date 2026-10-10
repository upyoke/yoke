"""Qualified instant and elapsed relative bounds for indexed event reads."""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from yoke_contracts.timestamps import parse_instant, utc_now

_UNIT_SECONDS = {"second": 1, "minute": 60, "hour": 3600, "day": 86400, "week": 604800}
_RELATIVE_RE = re.compile(
    r"^\s*(?P<amount>\d+)\s*"
    r"(?P<unit>second|minute|hour|day|week)s?\s+ago\s*$",
    re.IGNORECASE,
)


def parse_since(value: str, *, now: datetime | None = None) -> datetime:
    """Bind aware UTC bounds; days/weeks are elapsed 24-hour/seven-day windows.

    Absolute inputs require a qualified valid instant. An injected clock must
    also be aware; neither path guesses a timezone or loses microseconds.
    """
    if value is None or value == "":
        raise ValueError(
            "events: --since value is required; supply a qualified instant or elapsed relative range"
        )
    match = _RELATIVE_RE.fullmatch(value)
    if match:
        anchor = parse_instant(utc_now() if now is None else now)
        delta = timedelta(
            seconds=int(match.group("amount"))
            * _UNIT_SECONDS[match.group("unit").lower()]
        )
        return anchor - delta
    if not value[:1].isdigit():
        raise ValueError(
            f"events: unparseable --since value {value!r}; supply a qualified instant or N units ago"
        )
    return parse_instant(value)


__all__ = ["parse_since"]
