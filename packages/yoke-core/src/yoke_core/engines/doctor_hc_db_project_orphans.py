"""Orphaned project-reference health checks.

Orphan-reference HCs that detect rows referencing project IDs that no
longer exist:

- ``hc_orphaned_project_items`` — items with a project that's missing from
  the projects table.

Deployment evidence lives on ``deployment_runs`` / ``deployment_run_items``;
the retired deployment-event orphan branches scanned an events shape with
zero live rows and were deleted with the telemetry-only events cutover.
"""

from __future__ import annotations

from yoke_core.domain.db_helpers import query_rows

import yoke_core.engines.doctor_report as _base
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


def hc_orphaned_project_items(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-orphaned-project-items: Orphaned project references in items."""
    if not _base._table_exists(conn, "projects"):
        rec.record("HC-orphaned-project-items", "Orphaned project references in items", "PASS",
                    "projects table does not exist yet — skipping")
        return

    rows = query_rows(
        conn,
        "SELECT i.id, i.project_id FROM items i "
        "WHERE i.project_id IS NOT NULL "
        "AND NOT EXISTS (SELECT 1 FROM projects p WHERE p.id = i.project_id) "
        "ORDER BY i.id",
    )
    issues = [f"- YOK-{r['id']}: project_id '{r['project_id']}' does not exist" for r in rows]

    if issues:
        rec.record("HC-orphaned-project-items", "Orphaned project references in items", "WARN",
                    "\n".join(issues))
    else:
        rec.record("HC-orphaned-project-items", "Orphaned project references in items", "PASS", "")
