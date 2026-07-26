"""Backfill workflow-neutral item worktree lane records."""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.item_worktree_schema import ensure_item_worktree_schema
from yoke_core.domain.item_worktrees import (
    list_item_worktrees,
    record_item_worktree,
    validate_item_worktree_roles,
)
from yoke_core.domain.schema_common import _column_exists, _table_exists
from yoke_core.domain.workflow_behavior import (
    LANE_IMPLEMENTATION,
    LANE_INTEGRATION,
    LANE_WORKER,
    worktree_lane_policy,
)
from yoke_core.domain.workflow_runtime import load_item_workflow_runtime

MIGRATION_NAME = "workflow_item_worktree_records"


def _placeholder(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _item_lane_role(conn: Any, item_id: int) -> str:
    policy = worktree_lane_policy(load_item_workflow_runtime(conn, item_id))
    if LANE_IMPLEMENTATION in policy.allowed_roles:
        return LANE_IMPLEMENTATION
    return LANE_INTEGRATION


def _legacy_lane_rows(conn: Any) -> list[tuple[int, str, str | None]]:
    rows: list[tuple[int, str, str | None]] = []
    if _table_exists(conn, "epic_dispatch_chains"):
        rows.extend(
            (
                int(row[0]),
                str(row[1]),
                str(row[2]) if row[2] else None,
            )
            for row in conn.execute(
                "SELECT CAST(epic_id AS INTEGER), worktree, worktree_path "
                "FROM epic_dispatch_chains "
                "WHERE COALESCE(worktree, '') <> '' ORDER BY id"
            ).fetchall()
        )
    if _table_exists(conn, "epic_tasks"):
        branch_sql = (
            "COALESCE(NULLIF(branch, ''), NULLIF(worktree, ''), '')"
            if _column_exists(conn, "epic_tasks", "branch")
            else "COALESCE(worktree, '')"
        )
        path_sql = (
            "worktree_path"
            if _column_exists(conn, "epic_tasks", "worktree_path")
            else "NULL"
        )
        rows.extend(
            (
                int(row[0]),
                str(row[1]),
                str(row[2]) if row[2] else None,
            )
            for row in conn.execute(
                f"SELECT CAST(epic_id AS INTEGER), {branch_sql}, {path_sql} "
                "FROM epic_tasks "
                f"WHERE {branch_sql} <> '' ORDER BY id"
            ).fetchall()
        )
    return rows


def _backfill(conn: Any) -> None:
    if _column_exists(conn, "items", "worktree"):
        rows = conn.execute(
            "SELECT id, worktree FROM items "
            "WHERE COALESCE(worktree, '') <> '' ORDER BY id"
        ).fetchall()
        for item_id, branch in rows:
            record_item_worktree(
                conn,
                item_id=int(item_id),
                branch=str(branch),
                path=None,
                lane_role=_item_lane_role(conn, int(item_id)),
            )

    worker_items: set[int] = set()
    for item_id, branch, path in _legacy_lane_rows(conn):
        record_item_worktree(
            conn,
            item_id=item_id,
            branch=branch,
            path=path,
            lane_role=LANE_WORKER,
        )
        worker_items.add(item_id)

    for item_id in sorted(worker_items):
        policy = worktree_lane_policy(load_item_workflow_runtime(conn, item_id))
        active_roles = {
            str(row["lane_role"])
            for row in list_item_worktrees(conn, item_id, active_only=True)
        }
        if LANE_INTEGRATION not in policy.required_roles:
            continue
        if LANE_INTEGRATION not in active_roles:
            record_item_worktree(
                conn,
                item_id=item_id,
                branch=f"YOK-{item_id}-integration",
                path=None,
                lane_role=LANE_INTEGRATION,
            )


def _assert_legacy_rows_covered(conn: Any) -> None:
    marker = _placeholder(conn)
    if _column_exists(conn, "items", "worktree"):
        missing = conn.execute(
            "SELECT i.id, i.worktree FROM items i "
            "WHERE COALESCE(i.worktree, '') <> '' "
            "AND NOT EXISTS ("
            "SELECT 1 FROM item_worktrees iw "
            "WHERE iw.item_id = i.id AND iw.branch = i.worktree "
            "AND iw.state = 'active') "
            "ORDER BY i.id LIMIT 5"
        ).fetchall()
        if missing:
            raise AssertionError(
                "items.worktree rows lack universal lane records: "
                + ", ".join(f"{row[0]}:{row[1]}" for row in missing)
            )

    for item_id, branch, _path in _legacy_lane_rows(conn):
        row = conn.execute(
            "SELECT 1 FROM item_worktrees "
            f"WHERE item_id = {marker} AND branch = {marker} "
            "AND lane_role = 'worker' AND state = 'active'",
            (item_id, branch),
        ).fetchone()
        if row is None:
            raise AssertionError(
                f"legacy worker lane {item_id}:{branch} was not backfilled"
            )


def apply(conn: Any) -> None:
    """Create and populate universal lane ownership without dropping legacy."""
    before = {
        table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        for table in ("items", "epic_tasks", "epic_dispatch_chains")
        if _table_exists(conn, table)
    }
    ensure_item_worktree_schema(conn)
    _backfill(conn)
    _assert_legacy_rows_covered(conn)
    for (item_id,) in conn.execute(
        "SELECT DISTINCT item_id FROM item_worktrees "
        "WHERE state = 'active' ORDER BY item_id"
    ).fetchall():
        validate_item_worktree_roles(conn, int(item_id))
    after = {
        table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        for table in before
    }
    if after != before:
        raise AssertionError(
            f"legacy worktree source row counts changed: {before} -> {after}"
        )


def invariants(conn: Any) -> None:
    """Verify universal records cover every surviving legacy lane."""
    if not _table_exists(conn, "item_worktrees"):
        raise AssertionError("item_worktrees table is missing")
    _assert_legacy_rows_covered(conn)
    for (item_id,) in conn.execute(
        "SELECT DISTINCT item_id FROM item_worktrees "
        "WHERE state = 'active' ORDER BY item_id"
    ).fetchall():
        validate_item_worktree_roles(conn, int(item_id))


__all__ = ["MIGRATION_NAME", "apply", "invariants"]
