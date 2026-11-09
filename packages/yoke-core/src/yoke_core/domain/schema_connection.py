"""Dialect and instant adaptation for existing schema connections."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any

from yoke_contracts.timestamps import as_utc, format_instant


def connection_is_postgres(conn) -> bool:
    """Return the dialect of an *existing* connection by type, not env.

    Existing SQLite fixtures remain SQLite; all other connections are Postgres.
    """
    for attr in ("_inner", "_conn"):
        inner = getattr(conn, attr, None)
        if isinstance(inner, sqlite3.Connection):
            return False
    return not isinstance(conn, sqlite3.Connection)


def instant_parameter(
    conn: Any,
    value: datetime | None,
) -> datetime | str | None:
    """Bind an aware instant natively, or canonically at the SQLite boundary.

    SQL writers and comparison cutoffs pass native datetimes.
    Ingress must already have parsed its wire value; strings, epochs and naive
    datetimes refuse.
    """
    if value is None:
        return None
    instant = as_utc(value)
    return (
        instant if connection_is_postgres(conn) else format_instant(instant)
    )


