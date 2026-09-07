"""Work-claim row projections for the Sessions holdings reads."""

from __future__ import annotations

from typing import Any, Iterable, Optional

from yoke_core.domain.work_claim_targets import scope_int_sql, scope_text_sql


def _claim_rows(
    conn: Any,
    *,
    active_only: bool,
    session_ids: Optional[Iterable[str]] = None,
) -> list[Any]:
    """Read claims with decoded-key aliases needed by roster joins."""
    item_id = scope_int_sql(conn, "wc.scope", "item_id")
    epic_id = scope_int_sql(conn, "wc.scope", "epic_id")
    task_num = scope_int_sql(conn, "wc.scope", "task_num")
    process_key = scope_text_sql(conn, "wc.scope", "process_key")
    clauses: list[str] = []
    params: list[Any] = []
    if active_only:
        clauses.append("wc.released_at IS NULL")
    if session_ids is not None:
        ids = [str(session_id) for session_id in session_ids]
        if not ids:
            return []
        markers = ", ".join("%s" for _ in ids)
        clauses.append(f"wc.session_id IN ({markers})")
        params.extend(ids)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
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
        f") {where} ORDER BY wc.claimed_at {order}, wc.id {order}",
        tuple(params),
    ).fetchall()


def active_claim_rows(
    conn: Any, session_ids: Optional[Iterable[str]] = None,
) -> list[Any]:
    """Read only claims the session still holds."""
    return _claim_rows(conn, active_only=True, session_ids=session_ids)


def all_claim_rows(
    conn: Any, session_ids: Optional[Iterable[str]] = None,
) -> list[Any]:
    """Read current and released claims, newest first for history dedup."""
    return _claim_rows(conn, active_only=False, session_ids=session_ids)


__all__ = ["active_claim_rows", "all_claim_rows"]
