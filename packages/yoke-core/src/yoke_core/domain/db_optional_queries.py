"""Helpers for optional-table probes on native Postgres connections."""

from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Sequence

from yoke_core.domain import db_backend
from yoke_core.domain.db_savepoint import savepoint as open_savepoint


def fetch_optional_rows(
    conn: Any,
    sql: str,
    params: Sequence[Any] = (),
    *,
    savepoint: str,
) -> list:
    """Fetch rows from an optional relation without poisoning Postgres state.

    A missing relation reads as no rows; the caller's open transaction keeps
    its earlier writes.
    """
    guard = (
        open_savepoint(conn, savepoint, owns=False)
        if db_backend.connection_is_postgres(conn)
        else nullcontext()
    )
    try:
        with guard:
            return conn.execute(sql, tuple(params)).fetchall()
    except db_backend.operational_error_types(conn):
        return []


__all__ = ["fetch_optional_rows"]
