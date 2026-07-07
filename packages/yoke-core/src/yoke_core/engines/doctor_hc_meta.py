"""Meta health checks — backlog status, blocked items, dispatch chain, hygiene.

Core meta HC functions kept in this module:
``hc_status_consistency``, ``hc_blocked_items``, ``hc_dispatch_chain``,
``hc_backlog_hygiene``.

Backlog quality, lifecycle, and done-item run hygiene HCs live in focused
sibling modules and are re-exported here so ``doctor.py``'s registration
import block stays a single statement against ``doctor_hc_meta``:

- ``doctor_hc_meta_backlog`` — frontmatter schema, title length, backlog
  quality, per-epic validation.
- ``doctor_hc_meta_runs`` — undeployed/orphaned done items, deferred-items
  enforcement.
- ``doctor_hc_meta_lifecycle`` — shepherd lifecycle, lifecycle event continuity.
- ``doctor_hc_meta_epic`` — epic/worktree/project/vocabulary checks.
"""

from __future__ import annotations

from typing import List

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import query_rows, query_scalar

import yoke_core.engines.doctor_report as _base

from yoke_core.engines.doctor_report import (
    DoctorArgs,
    RecordCollector,
)

from yoke_core.engines.doctor_hc_meta_backlog import (  # noqa: F401
    hc_backlog_quality,
    hc_epic_validation,
    hc_frontmatter_schema,
    hc_title_length,
)
from yoke_core.engines.doctor_hc_meta_runs import (  # noqa: F401
    hc_deferred_items,
    hc_orphaned_done_items,
    hc_undeployed_done,
)
from yoke_core.engines.doctor_hc_meta_lifecycle import (  # noqa: F401
    hc_lifecycle_continuity,
    hc_shepherd_lifecycle,
)


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def hc_status_consistency(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-status-consistency: Backlog status consistency.

    Epic decomposition happens during ``/yoke shepherd`` (``refined-idea ->
    planning -> plan-drafted``), so epic_tasks rows do not exist at
    ``refined-idea``. The status filter starts at ``planning``.
    """
    issues: List[str] = []
    rows = query_rows(
        conn,
        "SELECT id, status, type FROM items "
        "WHERE status IN ('planning','implementing','reviewing-implementation') "
        "AND type='epic'",
    )
    for row in rows:
        item_id, status = row["id"], row["status"]
        task_count = query_scalar(
            conn,
            f"SELECT COUNT(*) FROM epic_tasks WHERE epic_id={_p(conn)}",
            (item_id,),
        )
        if not task_count or int(task_count) == 0:
            issues.append(f"- {item_id}: status is {status} but has no tasks in DB")
    if issues:
        rec.record("HC-status-consistency", "Backlog status consistency", "FAIL", "\n".join(issues))
    else:
        rec.record("HC-status-consistency", "Backlog status consistency", "PASS", "")


def hc_blocked_items(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-blocked-items: Blocked items check."""
    warn_items: List[str] = []
    fail_items: List[str] = []
    now = _base._now_epoch()
    # blocked is a flag; the legacy status='blocked' surface is
    # drift, owned by HC-blocked-status-drift. Read the flag here so we
    # only age out flag-driven blocks.
    rows = query_rows(
        conn,
        "SELECT id, status, updated_at FROM items WHERE blocked = 1",
    )
    for row in rows:
        item_id = row["id"]
        updated = row["updated_at"]
        if updated:
            upd_epoch = _base._iso_to_epoch(updated)
            if upd_epoch != 0:
                age_days = (now - upd_epoch) // 86400
                if age_days > 30:
                    fail_items.append(f"- {item_id}: blocked for {age_days} days (>30)")
                elif age_days > 7:
                    warn_items.append(f"- {item_id}: blocked for {age_days} days (>7)")
                else:
                    warn_items.append(f"- {item_id}: blocked ({age_days} days)")
            else:
                warn_items.append(f"- {item_id}: blocked (unknown duration — cannot parse updated timestamp)")
        else:
            warn_items.append(f"- {item_id}: blocked (no updated timestamp)")

    if fail_items:
        rec.record("HC-blocked-items", "Blocked items", "FAIL",
                    "\n".join(fail_items + warn_items))
    elif warn_items:
        rec.record("HC-blocked-items", "Blocked items", "WARN", "\n".join(warn_items))
    else:
        rec.record("HC-blocked-items", "Blocked items", "PASS", "")


def hc_dispatch_chain(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-dispatch-chain: Dispatch chain integrity."""
    issues: List[str] = []
    warnings: List[str] = []
    now = _base._now_epoch()

    # Check heartbeat freshness for in-progress tasks
    rows = query_rows(
        conn,
        "SELECT epic_id, task_num, title, status, last_heartbeat "
        "FROM epic_tasks WHERE status IN ('implementing','reviewing-implementation') "
        "ORDER BY epic_id, task_num",
    )
    for row in rows:
        hb = row["last_heartbeat"]
        if hb and hb != "null":
            hb_epoch = _base._iso_to_epoch(hb)
            if hb_epoch != 0:
                age_hrs = (now - hb_epoch) // 3600
                if age_hrs >= 2:
                    warnings.append(
                        f"- {row['epic_id']} task {row['task_num']} ({row['title']}): "
                        f"heartbeat is {age_hrs}h old (>2h threshold)"
                    )

    # Check task count consistency for epic items. Epic decomposition runs
    # in ``/yoke shepherd`` (``refined-idea -> planning``), so the filter
    # starts at ``planning``; ``refined-idea`` epics legitimately have no
    # epic_tasks rows yet.
    rows2 = query_rows(
        conn,
        "SELECT i.id, i.status, "
        "(SELECT COUNT(*) FROM epic_tasks WHERE epic_id=i.id) as task_count "
        "FROM items i WHERE i.type='epic' "
        "AND i.status IN ('planning','implementing','reviewing-implementation',"
        "'reviewed-implementation','polishing-implementation','implemented')",
    )
    for row in rows2:
        tc = row["task_count"]
        if not tc or int(tc) == 0:
            issues.append(
                f"- YOK-{row['id']}: epic is {row['status']} but has no tasks in DB"
            )

    if issues:
        rec.record("HC-dispatch-chain", "Dispatch chain integrity", "FAIL",
                    "\n".join(issues + warnings))
    elif warnings:
        rec.record("HC-dispatch-chain", "Dispatch chain integrity", "WARN",
                    "\n".join(warnings))
    else:
        rec.record("HC-dispatch-chain", "Dispatch chain integrity", "PASS", "")


def hc_backlog_hygiene(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-backlog-hygiene: Backlog hygiene."""
    issues: List[str] = []
    rows = query_rows(
        conn,
        "SELECT id, title, type, status, priority, github_issue FROM items",
    )
    for row in rows:
        item_id = row["id"]
        fname = f"{int(item_id):03d}.md" if str(item_id).isdigit() else f"{item_id}.md"
        if not row["id"]:
            issues.append(f"- {fname}: missing id field")
        if not row["title"]:
            issues.append(f"- {fname}: missing title field")
        if not row["type"]:
            issues.append(f"- {fname}: missing type field")
        if not row["status"]:
            issues.append(f"- {fname}: missing status field")
        if not row["priority"]:
            issues.append(f"- {fname}: missing priority field")

    if issues:
        rec.record("HC-backlog-hygiene", "Backlog hygiene", "WARN", "\n".join(issues))
    else:
        rec.record("HC-backlog-hygiene", "Backlog hygiene", "PASS", "")
