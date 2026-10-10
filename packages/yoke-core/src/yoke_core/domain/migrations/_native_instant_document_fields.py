"""Frozen historical instant validation and finite mutable-document helpers.

This code belongs to permanent migration history. It never relaxes future
writers and has no dependency on candidate runtime timestamp modules.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import re
from typing import Any

from psycopg import sql

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


@dataclass(frozen=True)
class DocumentUpdate:
    table: str
    key_column: str
    key: Any
    column: str
    before: str
    after: str


def _historical_clock(conn: Any, value: Any) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return format_instant(value)
    if not isinstance(value, str):
        return None
    try:
        return format_instant(value)
    except InvalidInstant:
        # This is a one-time UTC assumption, never an accepted future encoding.
        value = re.sub(r"([.][0-9]{6})[0-9]+", r"\1", value)
        valid = conn.execute(
            "SELECT pg_input_is_valid(%s,'timestamp with time zone')", (value,)
        ).fetchone()[0]
        if not valid:
            return None
        return format_instant(
            conn.execute("SELECT %s::timestamptz", (value,)).fetchone()[0]
        )


def _clock(
    conn: Any, value: Any, facts: tuple[Any, ...], *, optional=False
) -> str | None:
    if optional and (value is None or value == ""):
        return None
    for candidate in (value, *facts):
        repaired = _historical_clock(conn, candidate)
        if repaired is not None:
            return repaired
    raise RuntimeError(
        "instant_document_owner_fact_unavailable: a required owned clock has "
        "no usable historical value or owner fact. Recovery: inspect the restored "
        "owner record and declare its deterministic repair before rehearsal."
    )


def _rows(
    conn: Any,
    table: str,
    key: str,
    column: str,
    facts: tuple[str, ...],
    *,
    kind: str | None = None,
) -> list[Any]:
    names = {
        r[0]
        for r in conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name=%s",
            (table,),
        ).fetchall()
    }
    if not {key, column}.issubset(names) or (kind is not None and "kind" not in names):
        return []
    fields = [sql.Identifier(key), sql.Identifier(column)]
    fields += [
        sql.Identifier(name) if name in names else sql.SQL("NULL") for name in facts
    ]
    statement = sql.SQL("SELECT {} FROM {} WHERE {} IS NOT NULL AND {} <> ''").format(
        sql.SQL(",").join(fields),
        sql.Identifier(table),
        sql.Identifier(column),
        sql.Identifier(column),
    )
    if kind is not None:
        statement += sql.SQL(" AND kind=%s")
        return conn.execute(statement, (kind,)).fetchall()
    return conn.execute(statement).fetchall()


def _document(raw: str, table: str, key: Any) -> dict[str, Any]:
    try:
        value = json.loads(raw)
        if isinstance(value, dict):
            return value
    except (ValueError, TypeError):
        pass
    raise RuntimeError(
        f"instant_document_unreadable: {table} owner {key}. Recovery: inspect "
        "this restored mutable document before defining its repair; no data changed."
    )


def _add(
    updates: list[DocumentUpdate],
    table: str,
    key: str,
    row: Any,
    column: str,
    after: str,
) -> None:
    if row[1] != after:
        updates.append(DocumentUpdate(table, key, row[0], column, row[1], after))
