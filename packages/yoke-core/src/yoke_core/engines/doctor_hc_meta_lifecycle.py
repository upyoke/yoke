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
from yoke_core.domain.project_identity import render_item_ref
from yoke_core.domain.shepherd_segment import shepherd_edges
from yoke_core.domain.workflow_runtime import load_item_workflow_runtime

import yoke_core.engines.doctor_report as _base

from yoke_core.engines.doctor_report import (
    DoctorArgs,
    RecordCollector,
)
from yoke_core.engines.doctor_workflow_behavior import (
    rows_generating_task_graph,
)


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def hc_shepherd_lifecycle(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-shepherd-lifecycle: Shepherd lifecycle enforcement."""
    issues: List[str] = []
    min_item_id = _base._read_int_cutoff("hc_shepherd_lifecycle_min_item_id")
    rows = query_rows(
        conn,
        "SELECT id, status, workflow_id, workflow_version_id FROM items ORDER BY id",
    )
    for row in rows_generating_task_graph(conn, rows):
        if min_item_id is not None and row["id"] < min_item_id:
            continue
        runtime = load_item_workflow_runtime(conn, int(row["id"]))
        position = runtime.stage_index(str(row["status"]))
        if position is None:
            continue
        for edge in shepherd_edges(runtime):
            if position < runtime.stage_index(edge.target_stage):
                continue
            verdict = query_rows(
                conn,
                "SELECT id FROM shepherd_verdicts "
                f"WHERE item = {_p(conn)} AND transition = {_p(conn)} "
                "AND verdict IN ('READY','CAVEATS','SKIPPED') "
                "AND (verdict <> 'SKIPPED' OR LOWER(worker) IN ('review', 'architect')) LIMIT 1",
                (f"YOK-{row['id']}", edge.verdict_key),
            )
            if not verdict:
                issues.append(
                    f"- {render_item_ref(conn, row['id'])}: status is '{row['status']}' "
                    f"but no {edge.verdict_key} READY/CAVEATS/SKIPPED verdict found"
                )
                break

    if issues:
        rec.record(
            "HC-shepherd-lifecycle",
            "Shepherd lifecycle enforcement",
            "WARN",
            "\n".join(issues),
        )
    else:
        rec.record(
            "HC-shepherd-lifecycle", "Shepherd lifecycle enforcement", "PASS", ""
        )


def hc_lifecycle_continuity(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-lifecycle-continuity: status writes missing transition history."""
    if not _base._table_exists(conn, "item_status_transitions"):
        rec.record(
            "HC-lifecycle-continuity",
            "Lifecycle transition continuity",
            "PASS",
            "item_status_transitions table does not exist — skipping",
        )
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
            detail_lines.append(
                f"  - {render_item_ref(conn, row['id'])} ({row['status']}): {row['title']}"
            )
        detail = (
            f"{len(rows)} item(s) have status changes with no matching "
            "item_status_transitions row:\n"
            + "\n".join(detail_lines)
            + "\nRemediation: run yoke lifecycle repair-status <PREFIX-N> "
            '--to TARGET_STATUS --reason "reconcile lifecycle state" '
            "for targeted repair."
        )
        rec.record(
            "HC-lifecycle-continuity", "Lifecycle transition continuity", "WARN", detail
        )
    else:
        rec.record(
            "HC-lifecycle-continuity", "Lifecycle transition continuity", "PASS", ""
        )
