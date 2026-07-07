"""Meta health checks — epic_tasks cluster validation.

Cluster: HC checks operating on the ``epic_tasks`` table — worktree
backfill, empty-worktree detection, and orphan parent reconciliation.

HC functions: HC-epic-task-worktree, HC-empty-task-worktree,
HC-orphan-epic-tasks, HC-epic-task-worktree-backfill
"""

from __future__ import annotations

from typing import List

from yoke_core.domain.db_helpers import query_rows

import yoke_core.engines.doctor_report as _base

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
        "WHERE (et.worktree IS NULL OR et.worktree = '') "
        "AND i.status NOT IN ('idea','refining-idea','refined-idea','planning',"
        "'plan-drafted','refining-plan','planned','done','cancelled') "
        "ORDER BY et.epic_id, et.task_num",
    )

    if rows:
        epic_ids = sorted(set(str(r["epic_id"]) for r in rows))
        detail = (
            f"{len(rows)} epic_tasks row(s) with NULL worktree on active epics "
            f"(epic IDs: {','.join(epic_ids)})"
        )
        rec.record("HC-epic-task-worktree", "Epic task worktree backfill", "WARN", detail)
    else:
        rec.record("HC-epic-task-worktree", "Epic task worktree backfill", "PASS", "")



def hc_empty_task_worktree(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-empty-task-worktree: Epic tasks with empty worktree fields."""
    rows = query_rows(
        conn,
        "SELECT et.epic_id, et.task_num, et.status FROM epic_tasks et "
        "WHERE et.status IN ('implementing','reviewing-implementation') "
        "AND (et.worktree IS NULL OR et.worktree = '') "
        "ORDER BY et.epic_id, et.task_num",
    )

    issues = [
        f"- epic {r['epic_id']} task {r['task_num']}: status='{r['status']}' but worktree is empty"
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
    """HC-epic-task-worktree-backfill: Epic tasks with empty worktree fields."""
    issues: List[str] = []
    # Check if epic_tasks table has a worktree column
    if not _base._column_exists(conn, "epic_tasks", "worktree"):
        rec.record("HC-epic-task-worktree-backfill",
                    "Epic tasks with empty worktree fields", "PASS",
                    "epic_tasks.worktree column not present")
        return

    rows = query_rows(
        conn,
        "SELECT et.epic_id, et.task_num, et.title, i.id, i.status "
        "FROM epic_tasks et "
        "JOIN items i ON CAST(i.id AS TEXT) = CAST(et.epic_id AS TEXT) "
        "WHERE (et.worktree IS NULL OR et.worktree = '') "
        "AND i.status <> 'done' "
        "ORDER BY et.epic_id, et.task_num",
    )
    for row in rows:
        issues.append(
            f"- YOK-{row['id']} (epic={row['epic_id']}, status={row['status']}): "
            f"task {row['task_num']} '{row['title']}' has empty worktree"
        )

    if issues:
        rec.record("HC-epic-task-worktree-backfill",
                    "Epic tasks with empty worktree fields", "WARN",
                    "\n".join(issues))
    else:
        rec.record("HC-epic-task-worktree-backfill",
                    "Epic tasks with empty worktree fields", "PASS", "")
