"""Add explicit generated-task scope state and type every legacy task."""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.epic_task_scope import (
    SCOPE_STATES,
    TaskScopeRepairReport,
    repair_legacy_task_scopes,
)
from yoke_core.domain.schema_common import _column_exists, _table_exists


MIGRATION_NAME = "epic_task_scope_state"


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def apply(
    conn: Any,
    *,
    tenant_id: str | int = "current",
) -> TaskScopeRepairReport:
    """Install additive columns and idempotently type legacy rows."""
    if not _table_exists(conn, "epic_tasks"):
        raise RuntimeError("epic_task_scope_state requires epic_tasks")
    if not _table_exists(conn, "epic_task_files"):
        raise RuntimeError("epic_task_scope_state requires epic_task_files")
    if not _column_exists(conn, "epic_tasks", "scope_state"):
        conn.execute(
            "ALTER TABLE epic_tasks ADD COLUMN scope_state TEXT "
            "NOT NULL DEFAULT 'pending'"
        )
    if not _column_exists(conn, "epic_tasks", "scope_finalized_at"):
        conn.execute(
            "ALTER TABLE epic_tasks ADD COLUMN scope_finalized_at TEXT"
        )
    return repair_legacy_task_scopes(conn, tenant_id=tenant_id)


def invariants(conn: Any) -> None:
    """Require explicit, internally consistent legacy task scope."""
    for column in ("scope_state", "scope_finalized_at"):
        if not _column_exists(conn, "epic_tasks", column):
            raise AssertionError(f"epic_tasks.{column} is missing")
    placeholders = ",".join(_p(conn) for _ in SCOPE_STATES)
    invalid = conn.execute(
        "SELECT epic_id, task_num FROM epic_tasks "
        f"WHERE scope_state IS NULL OR scope_state NOT IN ({placeholders}) "
        "LIMIT 1",
        SCOPE_STATES,
    ).fetchone()
    if invalid is not None:
        raise AssertionError("epic_tasks contains invalid scope state")
    untyped = conn.execute(
        "SELECT epic_id, task_num FROM epic_tasks "
        "WHERE scope_state='pending' OR scope_finalized_at IS NULL LIMIT 1"
    ).fetchone()
    if untyped is not None:
        raise AssertionError(
            "legacy epic_tasks scope repair left an implicit task"
        )
    contradiction = conn.execute(
        "SELECT t.epic_id, t.task_num FROM epic_tasks t "
        "LEFT JOIN epic_task_files f ON f.epic_id=t.epic_id "
        "AND f.task_num=t.task_num "
        "GROUP BY t.epic_id, t.task_num, t.scope_state "
        "HAVING (t.scope_state='paths' AND "
        "COUNT(CASE WHEN TRIM(COALESCE(f.file_path, '')) <> '' THEN 1 END)=0) "
        "OR (t.scope_state='no_files' AND "
        "COUNT(CASE WHEN TRIM(COALESCE(f.file_path, '')) <> '' THEN 1 END)>0) "
        "LIMIT 1"
    ).fetchone()
    if contradiction is not None:
        raise AssertionError("epic_tasks scope contradicts epic_task_files")


__all__ = ["MIGRATION_NAME", "apply", "invariants"]
