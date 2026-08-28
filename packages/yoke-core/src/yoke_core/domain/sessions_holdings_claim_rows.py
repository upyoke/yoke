"""Work-claim row projections for the Sessions holdings reads."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.work_claim_targets import scope_int_sql, scope_text_sql


def _claim_rows(conn: Any, *, active_only: bool) -> list[Any]:
    """Read claims with decoded-key aliases needed by roster joins."""
    item_id = scope_int_sql(conn, "wc.scope", "item_id")
    epic_id = scope_int_sql(conn, "wc.scope", "epic_id")
    task_num = scope_int_sql(conn, "wc.scope", "task_num")
    process_key = scope_text_sql(conn, "wc.scope", "process_key")
    terminal_filter = "WHERE wc.released_at IS NULL" if active_only else ""
    order = "ASC" if active_only else "DESC"
    return conn.execute(
        f"SELECT wc.id, wc.session_id, wc.target_kind, wc.scope, "
        f"{item_id} AS item_id, {epic_id} AS epic_id, "
        f"{task_num} AS task_num, {process_key} AS process_key, "
        "wc.claimed_at, wc.released_at, wc.reason, "
        "COALESCE(task_lane.lane_role, item_lane.lane_role) AS lane_role "
        "FROM work_claims wc "
        "LEFT JOIN epic_tasks et ON wc.target_kind = 'epic_task' "
        f"AND et.epic_id = {epic_id} AND et.task_num = {task_num} "
        "LEFT JOIN item_worktrees task_lane "
        "ON task_lane.id = et.item_worktree_id "
        "AND task_lane.state = 'active' "
        "LEFT JOIN item_worktrees item_lane ON item_lane.id = ("
        "SELECT iw.id FROM item_worktrees iw "
        f"WHERE wc.target_kind = 'item' AND iw.item_id = {item_id} "
        "AND iw.state = 'active' "
        "ORDER BY CASE iw.lane_role WHEN 'integration' THEN 0 "
        "WHEN 'implementation' THEN 1 ELSE 2 END, iw.id LIMIT 1"
        f") {terminal_filter} ORDER BY wc.claimed_at {order}, wc.id {order}"
    ).fetchall()


def active_claim_rows(conn: Any) -> list[Any]:
    """Read only claims the session still holds."""
    return _claim_rows(conn, active_only=True)


def all_claim_rows(conn: Any) -> list[Any]:
    """Read current and released claims, newest first for history dedup."""
    return _claim_rows(conn, active_only=False)


__all__ = ["active_claim_rows", "all_claim_rows"]
