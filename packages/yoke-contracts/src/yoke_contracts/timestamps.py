"""Native domain instants and canonical UTC wire values.

Database writers bind aware ``datetime`` values. Owned JSON and files use
``YYYY-MM-DDTHH:MM:SS.ffffffZ`` or null. Calendar dates, elapsed durations,
monotonic clocks and externally specified epoch protocols have other owners.
"""

from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any


_QUALIFIED_INSTANT = re.compile(
    r"\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}"
    r"(?:\.\d{1,6})?(?:[Zz]|[+-]\d{2}:\d{2})\Z"
)


class InvalidInstant(ValueError):
    """An input cannot identify an instant without guessing its meaning."""

    code = "invalid_instant"

    def __init__(self) -> None:
        super().__init__(
            "invalid_instant: supply a valid RFC3339 timestamp with an explicit "
            "UTC offset and at most six fractional digits, or an aware datetime; "
            "use null only where the owning field permits absence."
        )


def utc_now() -> datetime:
    """Produce an aware UTC instant for native database binding."""
    return datetime.now(timezone.utc)


def as_utc(value: datetime) -> datetime:
    """Normalize an aware instant, refusing an implicit local timezone."""
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise InvalidInstant()
    return value.astimezone(timezone.utc)


def parse_instant(value: str | datetime) -> datetime:
    """Validate a supplied qualified instant and preserve its microseconds."""
    if isinstance(value, datetime):
        return as_utc(value)
    if not isinstance(value, str) or not _QUALIFIED_INSTANT.fullmatch(value):
        raise InvalidInstant()
    # RFC3339's -00:00 means the local offset is unknown, not known UTC.
    if value.endswith("-00:00"):
        raise InvalidInstant()
    if value[-6:-5] in ("+", "-") and (int(value[-5:-3]) > 23 or int(value[-2:]) > 59):
        raise InvalidInstant()
    try:
        parsed = datetime.fromisoformat(value.upper().replace("Z", "+00:00"))
    except ValueError:
        raise InvalidInstant() from None
    return as_utc(parsed)


def format_instant(value: str | datetime) -> str:
    """Express an instant in fixed-six UTC form without changing its meaning."""
    return (
        parse_instant(value).isoformat(timespec="microseconds").replace("+00:00", "Z")
    )


def iso8601_now() -> str:
    """Produce a canonical UTC wire timestamp; never a native DB value."""
    return format_instant(utc_now())


def temporal_wire(value: Any) -> Any:
    """Convert native result instants recursively at a JSON boundary.

    Strings are deliberately untouched: arbitrary prose, identifiers, and
    immutable historical documents are not timestamp fields. Owners parse
    qualified inputs before passing their native values to this boundary.
    """
    if isinstance(value, datetime):
        return format_instant(value)
    if isinstance(value, dict):
        return {key: temporal_wire(entry) for key, entry in value.items()}
    if isinstance(value, (list, tuple)):
        return [temporal_wire(entry) for entry in value]
    return value


__all__ = [
    "InvalidInstant",
    "as_utc",
    "format_instant",
    "iso8601_now",
    "parse_instant",
    "temporal_wire",
    "utc_now",
]
