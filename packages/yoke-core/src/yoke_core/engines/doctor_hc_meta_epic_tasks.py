"""Meta health checks — epic_tasks cluster validation.

Cluster: HC checks operating on the ``epic_tasks`` table — universal lane
linkage and orphan parent reconciliation.

HC functions: HC-epic-task-worktree, HC-empty-task-worktree,
HC-orphan-epic-tasks, HC-epic-task-worktree-backfill
"""

from __future__ import annotations

from typing import List

from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.schema_common import _column_exists

from yoke_core.engines.doctor_report import (
    DoctorArgs,
    RecordCollector,
)


def hc_epic_task_worktree(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-epic-task-worktree: Epic task worktree backfill."""
    rows = query_rows(
        conn,
        "SELECT et.epic_id, et.task_num FROM epic_tasks et "
        "JOIN items i ON i.id = et.epic_id "
        "LEFT JOIN item_worktrees iw ON iw.id = et.item_worktree_id "
        "WHERE (et.item_worktree_id IS NULL OR iw.id IS NULL) "
        "AND i.status NOT IN ('idea','refining-idea','refined-idea','planning',"
        "'plan-drafted','refining-plan','planned','done','cancelled') "
        "ORDER BY et.epic_id, et.task_num",
    )

    if rows:
        epic_ids = sorted(set(str(r["epic_id"]) for r in rows))
        detail = (
            f"{len(rows)} epic_tasks row(s) without a lane link on active epics "
            f"(epic IDs: {','.join(epic_ids)})"
        )
        rec.record("HC-epic-task-worktree", "Epic task worktree backfill", "WARN", detail)
    else:
        rec.record("HC-epic-task-worktree", "Epic task worktree backfill", "PASS", "")



def hc_empty_task_worktree(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-empty-task-worktree: Active epic tasks without active lane links."""
    rows = query_rows(
        conn,
        "SELECT et.epic_id, et.task_num, et.status FROM epic_tasks et "
        "LEFT JOIN item_worktrees iw ON iw.id = et.item_worktree_id "
        "WHERE et.status IN ('implementing','reviewing-implementation') "
        "AND (et.item_worktree_id IS NULL OR iw.id IS NULL "
        "OR iw.state <> 'active') "
        "ORDER BY et.epic_id, et.task_num",
    )

    issues = [
        f"- epic {r['epic_id']} task {r['task_num']}: status='{r['status']}' "
        "but no active lane is linked"
        for r in rows
    ]

    if issues:
        rec.record("HC-empty-task-worktree", "Epic tasks with empty worktree fields", "WARN",
                    "\n".join(issues))
    else:
        rec.record("HC-empty-task-worktree", "Epic tasks with empty worktree fields", "PASS", "")



def hc_orphan_epic_tasks(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-orphan-epic-tasks: Epic tasks whose parent item does not exist."""
    rows = query_rows(
        conn,
        "SELECT et.epic_id, et.task_num FROM epic_tasks et "
        "WHERE NOT EXISTS (SELECT 1 FROM items i WHERE i.id = et.epic_id) "
        "ORDER BY et.epic_id, et.task_num",
    )
    issues = [f"- epic {r['epic_id']} task {r['task_num']}: parent item does not exist" for r in rows]

    if issues:
        rec.record("HC-orphan-epic-tasks", "Orphan epic tasks", "WARN", "\n".join(issues))
    else:
        rec.record("HC-orphan-epic-tasks", "Orphan epic tasks", "PASS", "")



def hc_epic_task_worktree_backfill(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-epic-task-worktree-backfill: Epic tasks missing universal lane links."""
    issues: List[str] = []

    rows = query_rows(
        conn,
        "SELECT et.epic_id, et.task_num, et.title, i.id, i.status "
        "FROM epic_tasks et "
        "JOIN items i ON CAST(i.id AS TEXT) = CAST(et.epic_id AS TEXT) "
        "LEFT JOIN item_worktrees iw ON iw.id = et.item_worktree_id "
        "WHERE (et.item_worktree_id IS NULL OR iw.id IS NULL) "
        "AND i.status <> 'done' "
        "ORDER BY et.epic_id, et.task_num",
    )
    for row in rows:
        issues.append(
            f"- YOK-{row['id']} (epic={row['epic_id']}, status={row['status']}): "
            f"task {row['task_num']} '{row['title']}' has no lane link"
        )

    if issues:
        rec.record("HC-epic-task-worktree-backfill",
                    "Epic tasks with empty worktree fields", "WARN",
                    "\n".join(issues))
    else:
        rec.record("HC-epic-task-worktree-backfill",
                    "Epic tasks with empty worktree fields", "PASS", "")


def hc_epic_task_scope_state(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-epic-task-scope-state: generated-task scope is explicit and coherent."""
    title = "Generated task scope state"
    if not all(
        _column_exists(conn, "epic_tasks", column)
        for column in ("scope_state", "scope_finalized_at")
    ):
        rec.record(
            "HC-epic-task-scope-state",
            title,
            "WARN",
            "epic task scope migration has not installed both columns",
        )
        return
    rows = query_rows(
        conn,
        "SELECT et.epic_id, et.task_num, et.scope_state, i.status, "
        "COUNT(CASE WHEN TRIM(COALESCE(f.file_path, '')) <> '' "
        "THEN 1 END) AS file_count "
        "FROM epic_tasks et JOIN items i ON i.id=et.epic_id "
        "LEFT JOIN epic_task_files f ON f.epic_id=et.epic_id "
        "AND f.task_num=et.task_num "
        "GROUP BY et.epic_id, et.task_num, et.scope_state, "
        "et.scope_finalized_at, i.status "
        "HAVING (et.scope_state='paths' AND "
        "COUNT(CASE WHEN TRIM(COALESCE(f.file_path, '')) <> '' "
        "THEN 1 END)=0) "
        "OR (et.scope_state='no_files' AND "
        "COUNT(CASE WHEN TRIM(COALESCE(f.file_path, '')) <> '' "
        "THEN 1 END)>0) "
        "OR ((et.scope_state IN ('pending','legacy_deferred') "
        "OR et.scope_finalized_at IS NULL) "
        "AND i.status NOT IN ('idea','refining-idea','refined-idea',"
        "'planning','plan-drafted','done','cancelled','failed','stopped')) "
        "ORDER BY et.epic_id, et.task_num",
    )
    if rows:
        details = [
            f"- YOK-{row['epic_id']} task {row['task_num']}: "
            f"scope={row['scope_state']} files={row['file_count']} "
            f"item_status={row['status']}"
            for row in rows
        ]
        rec.record(
            "HC-epic-task-scope-state",
            title,
            "WARN",
            "\n".join(details),
        )
    else:
        rec.record("HC-epic-task-scope-state", title, "PASS", "")
