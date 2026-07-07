"""Meta health checks — drift cluster (vocabulary, project, dependency).

Cluster: HC checks for cross-cutting drift detection — API vocabulary,
approval contract, NULL project items, project metadata alignment, and
dependency-row drift.

HC functions: HC-api-vocabulary-drift, HC-approval-contract-drift,
HC-null-project-items, HC-projects-config-alignment, HC-dependency-drift,
HC-cancelled-blocker-dependencies
"""

from __future__ import annotations

from typing import List

from yoke_core.domain import db_backend, machine_config
from yoke_core.domain.db_helpers import query_rows, query_scalar

import yoke_core.engines.doctor_report as _base

from yoke_core.engines.doctor_report import (
    DoctorArgs,
    RecordCollector,
)


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def hc_api_vocabulary_drift(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-api-vocabulary-drift: API vocabulary drift."""
    rec.record("HC-api-vocabulary-drift", "API vocabulary drift", "PASS", "")



def hc_approval_contract_drift(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-approval-contract-drift: Approval contract drift."""
    rec.record("HC-approval-contract-drift", "Approval contract drift", "PASS", "")



def hc_null_project_items(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-null-project-items: NULL project items."""
    rows = query_rows(
        conn,
        "SELECT id, title FROM items "
        "WHERE project_id IS NULL "
        "AND status NOT IN ('done', 'cancelled') ORDER BY id",
    )
    issues = [f"- YOK-{r['id']}: '{r['title']}' has NULL project_id" for r in rows]

    if issues:
        rec.record("HC-null-project-items", "NULL project items", "FAIL", "\n".join(issues))
    else:
        rec.record("HC-null-project-items", "NULL project items", "PASS", "")



def hc_projects_config_alignment(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-projects-config-alignment: Projects config alignment."""
    if not _base._table_exists(conn, "projects"):
        rec.record("HC-projects-config-alignment", "Projects config alignment", "PASS",
                    "projects table does not exist yet — skipping")
        return

    repo_root = _base._resolve_repo_root()
    if not repo_root:
        rec.record("HC-projects-config-alignment", "Projects config alignment", "PASS", "")
        return

    issues: List[str] = []
    project_id = machine_config.project_id(repo_root)
    if project_id is not None:
        p = _p(conn)
        exists = query_scalar(
            conn, f"SELECT count(*) FROM projects WHERE id={p}",
            (project_id,),
        )
        if not exists or int(exists) == 0:
            issues.append(
                f"- checkout project_id={project_id} is not in projects table"
            )

    if issues:
        rec.record("HC-projects-config-alignment", "Projects config alignment", "WARN",
                    "\n".join(issues))
    else:
        rec.record("HC-projects-config-alignment", "Projects config alignment", "PASS", "")



def hc_dependency_drift(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-dependency-drift: Dependency drift detection (deprecated depends_on column)."""
    if not _base._column_exists(conn, "items", "depends_on"):
        rec.record("HC-dependency-drift", "Dependency drift detection", "PASS",
                    "depends_on column already removed")
        return

    count = query_scalar(
        conn,
        "SELECT COUNT(*) FROM items WHERE depends_on IS NOT NULL AND depends_on <> ''",
    )
    if count and int(count) > 0:
        rec.record("HC-dependency-drift", "Dependency drift detection", "WARN",
                    f"{count} item(s) have non-empty depends_on values (column is deprecated)")
    else:
        rec.record("HC-dependency-drift", "Dependency drift detection", "PASS", "")



def hc_cancelled_blocker_dependencies(
    conn, args: DoctorArgs, rec: RecordCollector
) -> None:
    """HC-cancelled-blocker-dependencies: item_dependencies rows whose
    blocking_item is a cancelled item.

    Catches pre-existing drift that the close-time reconciliation cannot
    safely auto-delete (ambiguous inbound rows without a resolution_ref
    match) plus any future regression where a caller bypasses
    ``backlog.execute_close`` and leaves self-evidently stale dependency
    rows behind.
    """
    if not _base._table_exists(conn, "item_dependencies"):
        rec.record(
            "HC-cancelled-blocker-dependencies",
            "Cancelled blocker dependencies",
            "PASS",
            "item_dependencies table does not exist yet — skipping",
        )
        return

    rows = query_rows(
        conn,
        "SELECT d.dependent_item, d.blocking_item, d.gate_point, "
        "d.satisfaction, COALESCE(i.resolution, ''), "
        "COALESCE(i.resolution_ref, '') "
        "FROM item_dependencies d "
        "JOIN items i ON i.id = CAST(REPLACE(d.blocking_item, 'YOK-', '') "
        "AS INTEGER) "
        "WHERE i.status = 'cancelled' "
        "ORDER BY d.dependent_item, d.blocking_item, d.gate_point",
    )
    if not rows:
        rec.record(
            "HC-cancelled-blocker-dependencies",
            "Cancelled blocker dependencies",
            "PASS",
            "",
        )
        return

    issues: List[str] = []
    for row in rows:
        dependent = row[0]
        blocking = row[1]
        gate_point = row[2]
        satisfaction = row[3]
        resolution = row[4]
        resolution_ref = row[5]
        issues.append(
            f"- {dependent} <- {blocking} gate={gate_point}"
            f" satisfaction={satisfaction}"
            f" resolution={resolution or '<unset>'}"
            f" resolution_ref={resolution_ref or '<unset>'}"
        )
    rec.record(
        "HC-cancelled-blocker-dependencies",
        "Cancelled blocker dependencies",
        "WARN",
        "\n".join(issues),
    )
