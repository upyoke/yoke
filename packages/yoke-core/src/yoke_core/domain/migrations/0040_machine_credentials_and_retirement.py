"""Bind API credentials to machines and preserve retired machine history."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.migration_serving_version import NEXT_RELEASE
from yoke_core.domain.schema_common import (
    _add_column_if_not_exists,
    _column_exists,
    _table_exists,
)


MINIMUM_SERVING_VERSION = NEXT_RELEASE
COLUMNS = {
    "api_tokens": (("machine_id", "TEXT DEFAULT NULL"),),
    "machines": (
        ("retired_at", "TEXT DEFAULT NULL"),
        ("retired_by_actor_id", "INTEGER DEFAULT NULL REFERENCES actors(id)"),
    ),
    "session_relays": (("credential_presence", "TEXT DEFAULT NULL"),),
}


def apply(conn: Any) -> None:
    """Add nullable ownership/retirement facts without rewriting history."""
    for table, columns in COLUMNS.items():
        if not _table_exists(conn, table):
            continue
        for column, ddl in columns:
            _add_column_if_not_exists(conn, table, column, ddl)
    if _table_exists(conn, "api_tokens"):
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_api_tokens_machine "
            "ON api_tokens(machine_id,status)"
        )
    if _table_exists(conn, "machines"):
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_machines_retired "
            "ON machines(retired_at,name)"
        )


def invariants(conn: Any) -> None:
    """Prove every machine-credential lifecycle column exists."""
    for table, columns in COLUMNS.items():
        if not _table_exists(conn, table):
            continue
        for column, _ddl in columns:
            assert _column_exists(conn, table, column), (
                f"{table}.{column} is missing after machine credential convergence"
            )


__all__ = ["COLUMNS", "MINIMUM_SERVING_VERSION", "apply", "invariants"]
