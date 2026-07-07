"""Helpers for optional-table probes on native Postgres connections."""

from __future__ import annotations

from typing import Any, Sequence

from yoke_core.domain import db_backend


def _rollback_savepoint(conn: Any, savepoint: str) -> None:
    try:
        conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
        conn.execute(f"RELEASE SAVEPOINT {savepoint}")
    except Exception:
        pass


def fetch_optional_rows(
    conn: Any,
    sql: str,
    params: Sequence[Any] = (),
    *,
    savepoint: str,
) -> list:
    """Fetch rows from an optional relation without poisoning Postgres state."""
    use_savepoint = db_backend.connection_is_postgres(conn)
    try:
        if use_savepoint:
            conn.execute(f"SAVEPOINT {savepoint}")
        rows = conn.execute(sql, tuple(params)).fetchall()
        if use_savepoint:
            conn.execute(f"RELEASE SAVEPOINT {savepoint}")
        return rows
    except db_backend.operational_error_types(conn):
        if use_savepoint:
            _rollback_savepoint(conn, savepoint)
        return []


__all__ = ["fetch_optional_rows"]
