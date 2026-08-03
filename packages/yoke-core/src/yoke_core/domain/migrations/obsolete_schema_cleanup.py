"""Shared helpers for removing verified-dead backlog schema residue."""

from __future__ import annotations

from typing import Any, Iterable

from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import (
    _column_exists,
    _get_check_constraint_defs,
    _table_exists,
)


def _identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _row_count(conn: Any, table: str) -> int:
    row = conn.execute(
        f"SELECT COUNT(*) FROM {_identifier(table)}"
    ).fetchone()
    return int(row[0])


def _require_table(conn: Any, table: str) -> None:
    if not _table_exists(conn, table):
        raise AssertionError(f"required migration table is missing: {table}")


def _require_columns(conn: Any, table: str, columns: Iterable[str]) -> None:
    missing = [column for column in columns if not _column_exists(conn, table, column)]
    if missing:
        raise AssertionError(
            f"{table} is missing current columns required by the cutover: "
            + ", ".join(missing)
        )


def _drop_column(conn: Any, table: str, column: str) -> None:
    if _column_exists(conn, table, column):
        conn.execute(
            f"ALTER TABLE {_identifier(table)} DROP COLUMN {_identifier(column)}"
        )


def _assert_columns_absent(conn: Any, table: str, columns: Iterable[str]) -> None:
    present = [column for column in columns if _column_exists(conn, table, column)]
    if present:
        raise AssertionError(
            f"retired columns remain on {table}: {', '.join(present)}"
        )


def _assert_row_count_unchanged(conn: Any, table: str, before: int) -> None:
    after = _row_count(conn, table)
    if after != before:
        raise AssertionError(
            f"{table} row count changed during schema cutover: {before} -> {after}"
        )


def apply_item_columns(conn: Any) -> None:
    _require_table(conn, "items")
    before = _row_count(conn, "items")
    _drop_column(conn, "items", "flow")
    _drop_column(conn, "items", "worktree")
    _assert_row_count_unchanged(conn, "items", before)
    _require_columns(
        conn,
        "items",
        ("status", "blocked", "blocked_reason", "workflow_id", "resolution"),
    )


def verify_item_columns(conn: Any) -> None:
    _require_table(conn, "items")
    _assert_columns_absent(conn, "items", ("flow", "worktree"))
    _require_columns(
        conn,
        "items",
        ("status", "blocked", "blocked_reason", "workflow_id", "resolution"),
    )


def apply_event_parent_id(conn: Any) -> None:
    _require_table(conn, "events")
    before = _row_count(conn, "events")
    _drop_column(conn, "events", "parent_id")
    _assert_row_count_unchanged(conn, "events", before)


def verify_event_parent_id(conn: Any) -> None:
    _require_table(conn, "events")
    _assert_columns_absent(conn, "events", ("parent_id",))


def apply_epic_task_blocked_by(conn: Any) -> None:
    _require_table(conn, "epic_tasks")
    before = _row_count(conn, "epic_tasks")
    _drop_column(conn, "epic_tasks", "blocked_by")
    _assert_row_count_unchanged(conn, "epic_tasks", before)
    _require_columns(conn, "epic_tasks", ("status",))


def verify_epic_task_blocked_by(conn: Any) -> None:
    _require_table(conn, "epic_tasks")
    _assert_columns_absent(conn, "epic_tasks", ("blocked_by",))
    _require_columns(conn, "epic_tasks", ("status",))
    definitions = _get_check_constraint_defs(conn, "epic_tasks")
    if definitions and not any(
        "status" in definition.lower() and "blocked" in definition.lower()
        for definition in definitions
    ):
        raise AssertionError("epic_tasks status check no longer permits blocked")


def _legacy_item_status_constraints(conn: Any) -> list[tuple[str, str]]:
    if not db_backend.connection_is_postgres(conn):
        return []
    rows = conn.execute(
        """
        SELECT con.conname, pg_catalog.pg_get_constraintdef(con.oid)
        FROM pg_catalog.pg_constraint con
        JOIN pg_catalog.pg_class cls ON cls.oid = con.conrelid
        JOIN pg_catalog.pg_namespace ns ON ns.oid = cls.relnamespace
        WHERE ns.nspname = current_schema()
          AND cls.relname = 'items'
          AND con.contype = 'c'
          AND pg_catalog.pg_get_constraintdef(con.oid) ILIKE %s
          AND pg_catalog.pg_get_constraintdef(con.oid) ILIKE %s
        ORDER BY con.conname
        """,
        ("%status%", "%blocked%"),
    ).fetchall()
    return [(str(row[0]), str(row[1])) for row in rows]


def _legacy_item_status_check_defs(conn: Any) -> list[str]:
    if not _table_exists(conn, "items"):
        return []
    return [
        definition
        for definition in _get_check_constraint_defs(conn, "items")
        if "status" in definition.lower() and "blocked" in definition.lower()
    ]


def _drop_legacy_item_status_checks(conn: Any) -> None:
    if db_backend.connection_is_postgres(conn):
        for name, _definition in _legacy_item_status_constraints(conn):
            conn.execute(
                f"ALTER TABLE {_identifier('items')} DROP CONSTRAINT "
                f"{_identifier(name)}"
            )
        return
    if _legacy_item_status_check_defs(conn):
        raise AssertionError(
            "SQLite validation surface contains an item status check with "
            "the retired blocked value; use the Postgres authority runner"
        )


def apply_item_blocked_lifecycle(conn: Any) -> None:
    _require_table(conn, "items")
    _require_table(conn, "epic_tasks")
    if _table_exists(conn, "lifecycle_enums"):
        _require_columns(conn, "lifecycle_enums", ("value",))
        marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
        conn.execute(
            f"DELETE FROM {_identifier('lifecycle_enums')} WHERE value={marker}",
            ("blocked",),
        )
    _drop_legacy_item_status_checks(conn)
    _require_columns(conn, "items", ("blocked", "blocked_reason", "resolution"))
    _require_columns(conn, "epic_tasks", ("status",))


def verify_item_blocked_lifecycle(conn: Any) -> None:
    _require_table(conn, "items")
    _require_table(conn, "epic_tasks")
    if _table_exists(conn, "lifecycle_enums"):
        _require_columns(conn, "lifecycle_enums", ("value",))
        marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
        row = conn.execute(
            f"SELECT COUNT(*) FROM {_identifier('lifecycle_enums')} "
            f"WHERE value={marker}",
            ("blocked",),
        ).fetchone()
        if int(row[0]) != 0:
            raise AssertionError("lifecycle_enums still contains blocked")
    if _legacy_item_status_constraints(conn) or _legacy_item_status_check_defs(conn):
        raise AssertionError("items still has an item-level blocked status check")
    _require_columns(conn, "items", ("blocked", "blocked_reason", "resolution"))
    _require_columns(conn, "epic_tasks", ("status",))
    definitions = _get_check_constraint_defs(conn, "epic_tasks")
    if definitions and not any(
        "status" in definition.lower() and "blocked" in definition.lower()
        for definition in definitions
    ):
        raise AssertionError("epic_tasks blocked status semantics were not preserved")


__all__ = [
    "apply_epic_task_blocked_by",
    "apply_event_parent_id",
    "apply_item_blocked_lifecycle",
    "apply_item_columns",
    "apply_path_claims_typed_owner_cleanup",
    "apply_wrapup_reports_drop",
    "verify_epic_task_blocked_by",
    "verify_event_parent_id",
    "verify_item_blocked_lifecycle",
    "verify_item_columns",
    "verify_path_claims_typed_owner_cleanup",
    "verify_wrapup_reports_drop",
]


def apply_path_claims_typed_owner_cleanup(conn: Any) -> None:
    _require_table(conn, "path_claims")
    before = _row_count(conn, "path_claims")
    for column in ("actor_id", "item_id", "session_id", "work_claim_id"):
        _drop_column(conn, "path_claims", column)
    _assert_row_count_unchanged(conn, "path_claims", before)
    _require_columns(
        conn,
        "path_claims",
        (
            "owner_kind",
            "owner_item_id",
            "owner_session_id",
            "owner_work_claim_id",
            "registered_by_actor_id",
            "registered_by_session_id",
        ),
    )


def verify_path_claims_typed_owner_cleanup(conn: Any) -> None:
    _require_table(conn, "path_claims")
    _assert_columns_absent(
        conn,
        "path_claims",
        ("actor_id", "item_id", "session_id", "work_claim_id"),
    )
    _require_columns(
        conn,
        "path_claims",
        (
            "owner_kind",
            "owner_item_id",
            "owner_session_id",
            "owner_work_claim_id",
            "registered_by_actor_id",
            "registered_by_session_id",
        ),
    )


def apply_wrapup_reports_drop(conn: Any) -> None:
    if not _table_exists(conn, "wrapup_reports"):
        return
    conn.execute(f"DROP TABLE {_identifier('wrapup_reports')}")


def verify_wrapup_reports_drop(conn: Any) -> None:
    if _table_exists(conn, "wrapup_reports"):
        raise AssertionError("wrapup_reports table still exists")
