"""Meta health checks — shepherd lifecycle and transition continuity.

Extracted from ``doctor_hc_meta`` to keep that module under the file-line cap.
This sibling owns the lifecycle-evidence HCs:

- ``hc_shepherd_lifecycle`` — shepherd verdict coverage for advanced epics.
- ``hc_lifecycle_continuity`` — item_status_transitions history coverage
  for every non-idea item status.

``doctor.py`` continues to import these symbols via ``doctor_hc_meta`` for
registration parity; this module is the authoritative source.
"""

from __future__ import annotations

from typing import List

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import query_rows

import yoke_core.engines.doctor_report as _base

from yoke_core.engines.doctor_report import (
    DoctorArgs,
    RecordCollector,
)


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def hc_shepherd_lifecycle(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-shepherd-lifecycle: Shepherd lifecycle enforcement."""
    issues: List[str] = []
    reported_ids = set()
    min_item_id = _base._read_int_cutoff("hc_shepherd_lifecycle_min_item_id")

    # Epics at 'planning' or later should have refined_idea_to_planning verdict
    rows = query_rows(
        conn,
        "SELECT i.id, i.status FROM items i "
        "WHERE i.type='epic' "
        "AND i.status NOT IN ('idea', 'refining-idea', 'refined-idea') "
        "AND NOT EXISTS ("
        "  SELECT 1 FROM shepherd_verdicts sv "
        "  WHERE sv.item = 'YOK-' || i.id "
        "  AND sv.transition = 'refined_idea_to_planning' "
        "  AND sv.verdict IN ('READY','CAVEATS')"
        ") ORDER BY i.id",
    )
    for row in rows:
        if min_item_id is not None and row["id"] < min_item_id:
            continue
        issues.append(
            f"- YOK-{row['id']}: status is '{row['status']}' but no "
            f"refined_idea_to_planning READY/CAVEATS verdict found"
        )
        reported_ids.add(row["id"])

    # Epics at 'plan-drafted' or later
    later_statuses = (
        "plan-drafted", "refining-plan", "planned", "implementing",
        "reviewing-implementation", "reviewed-implementation",
        "polishing-implementation", "implemented", "release", "done",
    )
    placeholders = ",".join(_p(conn) for _ in later_statuses)
    rows2 = query_rows(
        conn,
        f"SELECT i.id, i.status FROM items i "
        f"WHERE i.type='epic' "
        f"AND i.status IN ({placeholders}) "
        f"AND NOT EXISTS ("
        f"  SELECT 1 FROM shepherd_verdicts sv "
        f"  WHERE sv.item = 'YOK-' || i.id "
        f"  AND sv.transition = 'planning_to_plan_drafted' "
        f"  AND sv.verdict IN ('READY','CAVEATS')"
        f") ORDER BY i.id",
        later_statuses,
    )
    for row in rows2:
        if min_item_id is not None and row["id"] < min_item_id:
            continue
        if row["id"] not in reported_ids:
            issues.append(
                f"- YOK-{row['id']}: status is '{row['status']}' but no "
                f"planning_to_plan_drafted READY/CAVEATS verdict found"
            )

    if issues:
        rec.record("HC-shepherd-lifecycle", "Shepherd lifecycle enforcement", "WARN",
                    "\n".join(issues))
    else:
        rec.record("HC-shepherd-lifecycle", "Shepherd lifecycle enforcement", "PASS", "")


def hc_lifecycle_continuity(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-lifecycle-continuity: status writes missing transition history."""
    if not _base._table_exists(conn, "item_status_transitions"):
        rec.record("HC-lifecycle-continuity", "Lifecycle transition continuity", "PASS",
                    "item_status_transitions table does not exist — skipping")
        return

    # Cutoff suppresses pre-fix historical residue. items.updated_at is the
    # last-status-change timestamp; items whose current status was set before
    # the cutoff predate the writer fix and are grandfathered.
    min_updated_at = _base._read_str_cutoff(
        "hc_lifecycle_continuity_min_status_change_at",
    )
    cutoff_clause = f"AND i.updated_at >= {_p(conn)} " if min_updated_at else ""
    params: tuple = (min_updated_at,) if min_updated_at else ()

    rows = query_rows(
        conn,
        "SELECT i.id, i.title, i.status FROM items i "
        "WHERE i.status <> 'idea' AND i.status <> 'cancelled' "
        f"{cutoff_clause}"
        "AND NOT EXISTS ("
        "  SELECT 1 FROM item_status_transitions t "
        "  WHERE t.item_id = i.id AND t.task_num IS NULL "
        "  AND t.to_status = i.status"
        ") LIMIT 20",
        params,
    )
    if rows:
        detail_lines = []
        for row in rows:
            detail_lines.append(f"  - YOK-{row['id']} ({row['status']}): {row['title']}")
        detail = (
            f"{len(rows)} item(s) have status changes with no matching "
            "item_status_transitions row:\n"
            + "\n".join(detail_lines)
            + "\nRemediation: run python3 -m yoke_core.engines.repair_status <id> <status> "
            "for targeted repair."
        )
        rec.record("HC-lifecycle-continuity", "Lifecycle transition continuity", "WARN", detail)
    else:
        rec.record("HC-lifecycle-continuity", "Lifecycle transition continuity", "PASS", "")
