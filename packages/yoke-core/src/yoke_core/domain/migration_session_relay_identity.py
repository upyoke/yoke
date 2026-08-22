"""Relay identity convergence shared by ordered migration and invariants."""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import (
    _add_column_if_not_exists,
    _column_exists,
    _table_exists,
)


def converge_relay_identity(conn: Any) -> None:
    if not _table_exists(conn, "session_relays"):
        return
    _add_column_if_not_exists(
        conn,
        "session_relays",
        "actor_id",
        "INTEGER REFERENCES actors(id)",
    )
    _add_column_if_not_exists(conn, "session_relays", "hostname", "TEXT")
    assert_relay_identity(conn)
    if db_backend.connection_is_postgres(conn):
        conn.execute("ALTER TABLE session_relays ALTER COLUMN actor_id SET NOT NULL")
        conn.execute("ALTER TABLE session_relays ALTER COLUMN hostname SET NOT NULL")


def assert_relay_identity(conn: Any) -> None:
    for column in ("actor_id", "hostname"):
        if not _column_exists(conn, "session_relays", column):
            raise AssertionError(f"session_relays.{column} is required")
    missing = conn.execute(
        "SELECT COUNT(*) FROM session_relays "
        "WHERE actor_id IS NULL OR hostname IS NULL OR hostname=''"
    ).fetchone()[0]
    if missing:
        raise AssertionError("relay identity must be complete")


__all__ = ["assert_relay_identity", "converge_relay_identity"]
