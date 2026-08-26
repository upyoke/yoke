"""Active work-claim row projection for the Sessions holdings read."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.work_claim_targets import scope_int_sql, scope_text_sql


def active_claim_rows(conn: Any) -> list[Any]:
    """Read active claims with decoded-key aliases needed by roster joins."""
    item_id = scope_int_sql(conn, "wc.scope", "item_id")
    epic_id = scope_int_sql(conn, "wc.scope", "epic_id")
    task_num = scope_int_sql(conn, "wc.scope", "task_num")
    process_key = scope_text_sql(conn, "wc.scope", "process_key")
    return conn.execute(
        f"SELECT wc.session_id, wc.target_kind, wc.scope, "
        f"{item_id} AS item_id, {epic_id} AS epic_id, "
        f"{task_num} AS task_num, {process_key} AS process_key, "
        "wc.claimed_at, wc.reason, "
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
        ") WHERE wc.released_at IS NULL ORDER BY wc.claimed_at ASC"
    ).fetchall()


__all__ = ["active_claim_rows"]
