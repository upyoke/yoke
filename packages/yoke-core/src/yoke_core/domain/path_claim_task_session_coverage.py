"""Session-effective coverage for task-bound item path claims."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.path_claim_task_coverage import (
    eligible_task_status_clause,
    path_root_covers,
    task_budget_paths,
)
from yoke_core.domain.project_checkout_locations import worktree_path_for_branch


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _value(row: Any, key: str, position: int) -> Any:
    return row[key] if hasattr(row, "keys") else row[position]


def _target_lane(
    conn: Any,
    *,
    item_id: int,
    target_path: str,
    cwd: str,
) -> tuple[int, str] | None:
    candidate = str(target_path or "").strip()
    if candidate and not Path(candidate).is_absolute():
        candidate = str(Path(cwd or ".") / candidate)
    elif not candidate:
        candidate = cwd
    if not candidate:
        return None
    try:
        resolved_candidate = Path(candidate).expanduser().resolve()
    except OSError:
        return None
    marker = _p(conn)
    rows = conn.execute(
        "SELECT iw.id, iw.lane_role, iw.branch, iw.path, i.project_id "
        "FROM item_worktrees iw JOIN items i ON i.id = iw.item_id "
        f"WHERE iw.item_id = {marker} AND iw.state = 'active' "
        "ORDER BY iw.id",
        (int(item_id),),
    ).fetchall()
    matches: list[tuple[int, str, int]] = []
    for row in rows:
        raw_path = str(_value(row, "path", 3) or "").strip()
        lane_path = (
            Path(raw_path).expanduser()
            if raw_path
            else worktree_path_for_branch(
                int(_value(row, "project_id", 4)),
                str(_value(row, "branch", 2)),
            )
        )
        if lane_path is None:
            continue
        try:
            resolved_lane = lane_path.resolve()
            resolved_candidate.relative_to(resolved_lane)
        except (OSError, ValueError):
            continue
        matches.append(
            (
                int(_value(row, "id", 0)),
                str(_value(row, "lane_role", 1)),
                len(resolved_lane.parts),
            )
        )
    if not matches:
        return None
    lane_id, role, _depth = max(matches, key=lambda value: value[2])
    return lane_id, role


def _selected_tasks(
    conn: Any,
    *,
    session_id: str,
    item_id: int,
    lane_id: int,
    lane_role: str,
) -> tuple[int, ...]:
    marker = _p(conn)
    if lane_role == "integration":
        parent = conn.execute(
            "SELECT 1 FROM work_claims "
            f"WHERE session_id = {marker} AND target_kind = 'item' "
            f"AND item_id = {marker} AND released_at IS NULL LIMIT 1",
            (str(session_id), int(item_id)),
        ).fetchone()
        if parent is None:
            return ()
        rows = conn.execute(
            f"SELECT task_num FROM epic_tasks WHERE epic_id = {marker} "
            f"AND {eligible_task_status_clause()} "
            "ORDER BY task_num",
            (int(item_id),),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT DISTINCT wc.task_num FROM work_claims wc "
            "JOIN epic_tasks et "
            "  ON et.epic_id = wc.epic_id AND et.task_num = wc.task_num "
            f"WHERE wc.session_id = {marker} "
            "AND wc.target_kind = 'epic_task' "
            f"AND wc.epic_id = {marker} AND wc.released_at IS NULL "
            f"AND {eligible_task_status_clause('et.status')} "
            f"AND et.item_worktree_id = {marker} ORDER BY wc.task_num",
            (str(session_id), int(item_id), int(lane_id)),
        ).fetchall()
    return tuple(int(_value(row, "task_num", 0)) for row in rows)


def _active_bound_targets(
    conn: Any,
    *,
    item_id: int,
    task_nums: tuple[int, ...],
) -> dict[int, tuple[tuple[str, str], ...]]:
    if not task_nums:
        return {}
    marker = _p(conn)
    task_markers = ",".join(marker for _ in task_nums)
    rows = conn.execute(
        "SELECT b.task_num, pt.path_string, pt.kind "
        "FROM path_claim_task_bindings b "
        "JOIN path_claims pc ON pc.id = b.claim_id "
        "JOIN path_claim_targets pct ON pct.claim_id = pc.id "
        "JOIN path_targets pt ON pt.id = pct.target_id "
        f"WHERE b.epic_id = {marker} "
        f"AND b.task_num IN ({task_markers}) "
        "AND pc.state = 'active' AND pc.mode <> 'exception' "
        "ORDER BY b.task_num, pt.path_string",
        (int(item_id), *task_nums),
    ).fetchall()
    targets: dict[int, list[tuple[str, str]]] = {}
    for row in rows:
        targets.setdefault(int(_value(row, "task_num", 0)), []).append(
            (
                str(_value(row, "path_string", 1)),
                str(_value(row, "kind", 2)),
            )
        )
    return {
        task_num: tuple(dict.fromkeys(values)) for task_num, values in targets.items()
    }


def effective_targets_for_session(
    conn: Any,
    *,
    session_id: str,
    item_id: int,
    target_path: str,
    cwd: str,
) -> tuple[tuple[str, str], ...]:
    """Return worker-task intersection or persisted integration-lane union.

    An integration lane is selected only through the existing relational
    authority ``epic_tasks.item_worktree_id -> item_worktrees.lane_role``.
    """
    lane = _target_lane(
        conn,
        item_id=int(item_id),
        target_path=str(target_path),
        cwd=str(cwd),
    )
    if lane is None:
        return ()
    lane_id, lane_role = lane
    selected = _selected_tasks(
        conn,
        session_id=str(session_id),
        item_id=int(item_id),
        lane_id=lane_id,
        lane_role=lane_role,
    )
    if not selected:
        return ()
    targets = _active_bound_targets(
        conn,
        item_id=int(item_id),
        task_nums=selected,
    )
    effective: list[tuple[str, str]] = []
    for task_num in selected:
        for root, kind in targets.get(task_num, ()):
            for budget_path in task_budget_paths(conn, item_id, task_num):
                if path_root_covers(root, budget_path, kind=kind):
                    budget_kind = "directory" if budget_path.endswith("/") else "file"
                    effective.append((budget_path, budget_kind))
    return tuple(sorted(dict.fromkeys(effective)))


def effective_paths_for_session(
    conn: Any,
    *,
    session_id: str,
    item_id: int,
    target_path: str,
    cwd: str,
) -> tuple[str, ...]:
    """Compatibility projection of effective task targets."""
    return tuple(
        path
        for path, _kind in effective_targets_for_session(
            conn,
            session_id=session_id,
            item_id=item_id,
            target_path=target_path,
            cwd=cwd,
        )
    )


__all__ = ["effective_paths_for_session", "effective_targets_for_session"]
