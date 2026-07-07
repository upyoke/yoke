"""Stamp harness sessions with client-resolved project identity."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.schema_common import (
    _column_exists,
    _column_is_not_null,
    _get_indexes,
    _table_exists,
)

_TABLE = "harness_sessions"
_COLUMN = "project_id"
_INDEX = "idx_harness_sessions_project"
_FK = "harness_sessions_project_id_fkey"
_PRIMARY_PROJECT_ID = 1
_PRIMARY_PROJECT_SLUG = "yoke"


def apply(conn: Any) -> None:
    """Enforce non-null session project identity."""
    if not _table_exists(conn, _TABLE):
        raise AssertionError(f"{_TABLE} table is required before this migration")
    _assert_primary_project_identity(conn)
    if not _column_exists(conn, _TABLE, _COLUMN):
        conn.execute(f"ALTER TABLE {_TABLE} ADD COLUMN {_COLUMN} INTEGER DEFAULT NULL")
    _assert_no_unmapped_sessions(conn)
    _add_foreign_key(conn)
    conn.execute(
        f"CREATE INDEX IF NOT EXISTS {_INDEX} ON {_TABLE}({_COLUMN})"
    )
    conn.execute(f"ALTER TABLE {_TABLE} ALTER COLUMN {_COLUMN} SET NOT NULL")


def invariants(conn: Any) -> None:
    """Verify the session project identity shape is present."""
    _assert_primary_project_identity(conn)
    if not _column_exists(conn, _TABLE, _COLUMN):
        raise AssertionError(f"{_TABLE}.{_COLUMN} is missing")
    if not _column_is_not_null(conn, _TABLE, _COLUMN):
        raise AssertionError(f"{_TABLE}.{_COLUMN} is nullable")
    if _INDEX not in set(_get_indexes(conn, _TABLE)):
        raise AssertionError(f"{_INDEX} is missing")
    if not _foreign_key_exists(conn):
        raise AssertionError(f"{_FK} is missing")
    _assert_no_unmapped_sessions(conn)


def _assert_primary_project_identity(conn: Any) -> None:
    row = conn.execute(
        "SELECT id FROM projects WHERE slug = %s",
        (_PRIMARY_PROJECT_SLUG,),
    ).fetchone()
    if row is None:
        raise AssertionError("primary project slug yoke is missing")
    if int(_row_value(row, "id", 0)) != _PRIMARY_PROJECT_ID:
        raise AssertionError("primary project slug yoke must retain project id 1")


def _assert_no_unmapped_sessions(conn: Any) -> None:
    rows = conn.execute(
        f"SELECT session_id, workspace FROM {_TABLE} "
        f"WHERE {_COLUMN} IS NULL ORDER BY session_id LIMIT 5"
    ).fetchall()
    if rows:
        samples = ", ".join(
            f"{_row_value(row, 'session_id', 0)}@{_row_value(row, 'workspace', 1)}"
            for row in rows
        )
        raise AssertionError(f"unstamped harness sessions remain: {samples}")


def _foreign_key_exists(conn: Any) -> bool:
    row = conn.execute(
        """
        SELECT 1
        FROM pg_catalog.pg_constraint con
        JOIN pg_catalog.pg_class rel ON rel.oid = con.conrelid
        JOIN pg_catalog.pg_namespace ns ON ns.oid = rel.relnamespace
        WHERE ns.nspname = current_schema()
          AND rel.relname = %s
          AND con.conname = %s
          AND con.contype = 'f'
        """,
        (_TABLE, _FK),
    ).fetchone()
    return row is not None


def _add_foreign_key(conn: Any) -> None:
    if _foreign_key_exists(conn):
        return
    conn.execute(
        f"ALTER TABLE {_TABLE} ADD CONSTRAINT {_FK} "
        f"FOREIGN KEY ({_COLUMN}) REFERENCES projects(id)"
    )


def _row_value(row: Any, key: str, index: int) -> Any:
    return row[key] if hasattr(row, "keys") else row[index]
