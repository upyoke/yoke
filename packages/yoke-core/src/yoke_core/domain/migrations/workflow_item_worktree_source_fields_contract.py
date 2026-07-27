"""Remove superseded worktree source fields after universal references are live."""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.migrations.workflow_item_worktree_records import (
    invariants as assert_worktree_records,
)
from yoke_core.domain.schema_common import _column_exists, _table_exists

MIGRATION_NAME = "workflow_item_worktree_source_fields_contract"

_REQUIRED_REFERENCE_COLUMNS = (
    ("epic_tasks", "item_worktree_id"),
    ("epic_dispatch_chains", "item_worktree_id"),
)
_REQUIRED_REFERENCE_CONSTRAINTS = (
    ("epic_tasks", "fk_epic_tasks_item_worktree"),
    ("epic_dispatch_chains", "fk_epic_dispatch_chains_item_worktree"),
)
_RETIRED_COLUMNS = (
    ("item_worktrees", "session_id"),
    ("epic_tasks", "worktree"),
    ("epic_tasks", "branch"),
    ("epic_tasks", "worktree_path"),
    ("epic_dispatch_chains", "worktree"),
    ("epic_dispatch_chains", "worktree_path"),
)
_TABLES = ("item_worktrees", "epic_tasks", "epic_dispatch_chains")


def _quote_identifier(raw: str) -> str:
    return '"' + raw.replace('"', '""') + '"'


def _row_counts(conn: Any) -> dict[str, int]:
    return {
        table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        for table in _TABLES
    }


def _assert_row_counts(conn: Any, expected: dict[str, int]) -> None:
    actual = _row_counts(conn)
    if actual != expected:
        raise AssertionError(
            f"worktree source contraction changed row counts: {expected} -> {actual}"
        )


def _reference_constraint_exists(
    conn: Any,
    *,
    table: str,
    constraint: str,
) -> bool:
    row = conn.execute(
        "SELECT 1 "
        "FROM pg_catalog.pg_constraint con "
        "JOIN pg_catalog.pg_class source_rel ON source_rel.oid=con.conrelid "
        "JOIN pg_catalog.pg_namespace source_ns "
        "ON source_ns.oid=source_rel.relnamespace "
        "JOIN pg_catalog.pg_attribute source_col "
        "ON source_col.attrelid=con.conrelid "
        "AND source_col.attnum=con.conkey[1] "
        "JOIN pg_catalog.pg_class target_rel ON target_rel.oid=con.confrelid "
        "JOIN pg_catalog.pg_namespace target_ns "
        "ON target_ns.oid=target_rel.relnamespace "
        "JOIN pg_catalog.pg_attribute target_col "
        "ON target_col.attrelid=con.confrelid "
        "AND target_col.attnum=con.confkey[1] "
        "WHERE source_ns.nspname=current_schema() "
        "AND target_ns.nspname=current_schema() "
        "AND source_rel.relname=%s "
        "AND target_rel.relname='item_worktrees' "
        "AND con.conname=%s "
        "AND con.contype='f' "
        "AND array_length(con.conkey, 1)=1 "
        "AND array_length(con.confkey, 1)=1 "
        "AND source_col.attname='item_worktree_id' "
        "AND target_col.attname='id'",
        (table, constraint),
    ).fetchone()
    return row is not None


def _assert_required_shape(conn: Any) -> None:
    if not db_backend.connection_is_postgres(conn):
        raise RuntimeError("worktree source-field contraction requires PostgreSQL")
    for table in _TABLES:
        if not _table_exists(conn, table):
            raise AssertionError(f"{table} is required before contraction")
    for table, column in _REQUIRED_REFERENCE_COLUMNS:
        if not _column_exists(conn, table, column):
            raise AssertionError(f"{table}.{column} is required before contraction")
    for table, constraint in _REQUIRED_REFERENCE_CONSTRAINTS:
        if not _reference_constraint_exists(
            conn,
            table=table,
            constraint=constraint,
        ):
            raise AssertionError(
                f"{table} lacks required item-worktree reference {constraint}"
            )


def apply(conn: Any) -> None:
    """Drop superseded sources only after every usable lane is represented."""
    _assert_required_shape(conn)
    conn.execute(
        "LOCK TABLE item_worktrees, epic_tasks, epic_dispatch_chains "
        "IN ACCESS EXCLUSIVE MODE"
    )
    _assert_required_shape(conn)
    before = _row_counts(conn)
    assert_worktree_records(conn)

    for table, column in _RETIRED_COLUMNS:
        if _column_exists(conn, table, column):
            conn.execute(
                f"ALTER TABLE {_quote_identifier(table)} "
                f"DROP COLUMN {_quote_identifier(column)}"
            )

    _assert_row_counts(conn, before)
    invariants(conn)


def invariants(conn: Any) -> None:
    """Verify universal references are the remaining worktree authority."""
    _assert_required_shape(conn)
    remaining = [
        f"{table}.{column}"
        for table, column in _RETIRED_COLUMNS
        if _column_exists(conn, table, column)
    ]
    if remaining:
        raise AssertionError(
            "superseded worktree source fields are still present: "
            + ", ".join(remaining)
        )
    assert_worktree_records(conn)


__all__ = ["MIGRATION_NAME", "apply", "invariants"]
