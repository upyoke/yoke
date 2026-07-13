"""Converge the function-call ledger onto its canonical physical layout."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.schema_common import _table_exists


TABLE = "function_call_ledger"
TARGET_TABLE = "function_call_ledger_layout_target"
TARGET_PRIMARY_KEY = "function_call_ledger_layout_target_pkey"
EXPECTED_COLUMNS = (
    "request_id",
    "function_id",
    "actor_id",
    "authorization_scope",
    "payload_checksum",
    "result",
    "created_at",
)


def apply(conn: Any) -> None:
    """Rebuild only a complete ledger whose columns are physically reordered."""

    if not _table_exists(conn, TABLE):
        raise AssertionError(f"{TABLE} table is required before this migration")
    actual = column_order(conn, TABLE)
    if actual == EXPECTED_COLUMNS:
        invariants(conn)
        return
    if set(actual) != set(EXPECTED_COLUMNS) or len(actual) != len(EXPECTED_COLUMNS):
        missing = sorted(set(EXPECTED_COLUMNS) - set(actual))
        extra = sorted(set(actual) - set(EXPECTED_COLUMNS))
        raise AssertionError(
            f"{TABLE} columns differ beyond order (missing={missing}, extra={extra})"
        )

    conn.execute(f"LOCK TABLE {TABLE} IN ACCESS EXCLUSIVE MODE")
    if _table_exists(conn, TARGET_TABLE):
        raise AssertionError(f"unexpected migration target table {TARGET_TABLE}")
    conn.execute(
        f"CREATE TABLE {TARGET_TABLE} ("
        "request_id TEXT NOT NULL, "
        "function_id TEXT NOT NULL, "
        "actor_id TEXT NOT NULL DEFAULT '', "
        "authorization_scope TEXT NOT NULL DEFAULT '', "
        "payload_checksum TEXT NOT NULL DEFAULT '', "
        "result TEXT, "
        "created_at TEXT NOT NULL, "
        f"CONSTRAINT {TARGET_PRIMARY_KEY} PRIMARY KEY (request_id))"
    )
    columns = ", ".join(EXPECTED_COLUMNS)
    conn.execute(
        f"INSERT INTO {TARGET_TABLE} ({columns}) SELECT {columns} FROM {TABLE}"
    )
    if _count(conn, TABLE) != _count(conn, TARGET_TABLE):
        raise AssertionError(f"{TABLE} row count changed during layout convergence")
    differences = _count_query(
        conn,
        f"SELECT COUNT(*) FROM ((SELECT {columns} FROM {TABLE} EXCEPT "
        f"SELECT {columns} FROM {TARGET_TABLE}) UNION ALL "
        f"(SELECT {columns} FROM {TARGET_TABLE} EXCEPT "
        f"SELECT {columns} FROM {TABLE})) AS differences",
    )
    if differences:
        raise AssertionError(f"{TABLE} content changed during layout convergence")

    conn.execute(f"DROP TABLE {TABLE}")
    conn.execute(f"ALTER TABLE {TARGET_TABLE} RENAME TO {TABLE}")
    conn.execute(
        f"ALTER TABLE {TABLE} RENAME CONSTRAINT {TARGET_PRIMARY_KEY} TO {TABLE}_pkey"
    )
    conn.execute(f"CREATE INDEX idx_{TABLE}_created ON {TABLE}(created_at)")
    invariants(conn)


def invariants(conn: Any) -> None:
    """Verify exact columns plus the two canonical ledger indexes."""

    if not _table_exists(conn, TABLE):
        raise AssertionError(f"{TABLE} table is missing")
    actual = column_order(conn, TABLE)
    if actual != EXPECTED_COLUMNS:
        raise AssertionError(
            f"{TABLE} physical columns are {actual}; expected {EXPECTED_COLUMNS}"
        )
    if _table_exists(conn, TARGET_TABLE):
        raise AssertionError(f"migration target table {TARGET_TABLE} still exists")
    index_names = {
        str(row[0])
        for row in conn.execute(
            "SELECT indexname FROM pg_indexes "
            "WHERE schemaname = current_schema() AND tablename = %s",
            (TABLE,),
        ).fetchall()
    }
    expected_indexes = {f"{TABLE}_pkey", f"idx_{TABLE}_created"}
    if index_names != expected_indexes:
        raise AssertionError(
            f"{TABLE} indexes are {sorted(index_names)}; "
            f"expected {sorted(expected_indexes)}"
        )


def column_order(conn: Any, table: str) -> tuple[str, ...]:
    rows = conn.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = %s "
        "ORDER BY ordinal_position",
        (table,),
    ).fetchall()
    return tuple(str(row[0]) for row in rows)


def _count(conn: Any, table: str) -> int:
    return _count_query(conn, f"SELECT COUNT(*) FROM {table}")


def _count_query(conn: Any, statement: str) -> int:
    row = conn.execute(statement).fetchone()
    return int(row[0]) if row is not None else 0


__all__ = [
    "EXPECTED_COLUMNS",
    "TABLE",
    "TARGET_PRIMARY_KEY",
    "TARGET_TABLE",
    "apply",
    "column_order",
    "invariants",
]
