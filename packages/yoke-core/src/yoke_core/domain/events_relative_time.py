"""Relative-time parser for ``events list --since`` / ``--until``.

Without parsing, ``2 hours ago`` sorts lexicographically before every
ISO timestamp (``2026-...``) and the SQL ``created_at >= %s`` predicate
matches every row. This helper canonicalizes ISO-8601 (passthrough) or
``N units ago`` (resolved against ``now``) to an ISO UTC string. The
``now`` keyword is injected by tests; production callers omit it.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Optional


_UNIT_SECONDS: dict[str, int] = {
    "second": 1,
    "minute": 60,
    "hour": 3600,
    "day": 86_400,
    "week": 604_800,
}


# ``N (units) ago`` — units may be singular or plural and case-insensitive.
_RELATIVE_RE = re.compile(
    r"^\s*(?P<amount>\d+)\s*"
    r"(?P<unit>second|minute|hour|day|week)s?\s+ago\s*$",
    re.IGNORECASE,
)


# An ISO-8601 prefix is anything that begins with four digits (a year).
# The helper does NOT validate full ISO syntax — SQLite's date functions
# do the heavy lifting downstream — but the leading-year shape is
# enough to disambiguate ISO from the ``N units ago`` form.
_ISO_PREFIX_RE = re.compile(r"^\d{4}")


def parse_since(value: str, *, now: Optional[datetime] = None) -> str:
    """Resolve a ``--since`` / ``--until`` value to an ISO-8601 UTC string.

    Accepts:

    * Any ISO-8601 timestamp (passed through verbatim — the helper does
      not normalize trailing-Z vs ``+00:00``; the operator's literal
      input round-trips into the SQL bind).
    * ``N (second|minute|hour|day|week)[s] ago`` (case-insensitive,
      singular or plural).

    Raises ``ValueError`` with a clear message on any other input. The
    fail-closed contract mirrors ``events_queries._build_where`` so
    unknown flag values do not silently produce unfiltered results.
    """
    if value is None or value == "":
        raise ValueError("events: --since value is required")
    if _ISO_PREFIX_RE.match(value):
        return value
    match = _RELATIVE_RE.match(value)
    if not match:
        raise ValueError(
            f"events: unparseable --since value {value!r}"
        )
    amount = int(match.group("amount"))
    unit = match.group("unit").lower()
    delta = timedelta(seconds=amount * _UNIT_SECONDS[unit])
    anchor = now if now is not None else datetime.now(timezone.utc)
    if anchor.tzinfo is None:
        anchor = anchor.replace(tzinfo=timezone.utc)
    resolved = anchor - delta
    # ISO-8601 with a trailing Z so the result string sorts correctly
    # against the canonical Yoke event timestamps written elsewhere.
    return resolved.strftime("%Y-%m-%dT%H:%M:%SZ")


__all__ = ["parse_since"]
