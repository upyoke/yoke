"""Database health checks — QA requirements and smoke artifacts.

HC functions covering QA-related deployment-run integrity:
- ``hc_run_qa_unsatisfied`` — succeeded runs with pending blocking QA.
- ``hc_validation_no_qa_reqs`` — items in reviewing-implementation lacking QA reqs.
- ``hc_smoke_failure_stale`` — stale smoke QA requirements.
- ``hc_smoke_artifact_orphan`` — orphaned QA artifacts.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.time_parse import age_hours_since

import yoke_core.engines.doctor_report as _base

from yoke_core.engines.doctor_report import (
    DoctorArgs,
    RecordCollector,
)


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def hc_run_qa_unsatisfied(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-run-qa-unsatisfied: Succeeded runs with pending blocking QA."""
    if not _base._table_exists(conn, "deployment_run_qa"):
        rec.record("HC-run-qa-unsatisfied", "Succeeded runs with pending blocking QA", "PASS",
                    "deployment_run_qa table does not exist — skipping")
        return

    issues: List[str] = []
    rows = query_rows(
        conn,
        "SELECT dr.id, COALESCE(p.slug, CAST(dr.project_id AS TEXT)) AS project, "
        "STRING_AGG(CAST(drq.check_name AS TEXT), ', ') as checks "
        "FROM deployment_runs dr "
        "LEFT JOIN projects p ON p.id = dr.project_id "
        "JOIN deployment_run_qa drq ON drq.run_id = dr.id "
        "WHERE dr.status = 'succeeded' AND drq.blocking = 1 AND drq.status = 'pending' "
        "GROUP BY dr.id, p.slug, dr.project_id ORDER BY dr.id",
    )
    for row in rows:
        issues.append(
            f"- run '{row['id']}': project={row['project']}, pending blocking QA: {row['checks']}"
        )

    if issues:
        rec.record("HC-run-qa-unsatisfied", "Succeeded runs with pending blocking QA", "WARN",
                    "\n".join(issues))
    else:
        rec.record("HC-run-qa-unsatisfied", "Succeeded runs with pending blocking QA", "PASS", "")



def hc_validation_no_qa_reqs(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-validation-no-qa-reqs: Items in reviewing-implementation without QA requirements."""
    if not _base._table_exists(conn, "qa_requirements"):
        rec.record("HC-validation-no-qa-reqs",
                    "Items in reviewing-implementation without QA requirements", "PASS",
                    "qa_requirements table does not exist yet — skipping")
        return

    issues: List[str] = []
    # Items
    rows = query_rows(
        conn,
        "SELECT i.id, i.title FROM items i "
        "WHERE i.status = 'reviewing-implementation' "
        "AND NOT EXISTS (SELECT 1 FROM qa_requirements qr WHERE qr.item_id = i.id) "
        "ORDER BY i.id",
    )
    for row in rows:
        issues.append(
            f"- YOK-{row['id']}: '{row['title']}' — in reviewing-implementation with zero qa_requirements"
        )

    # Epic tasks
    task_rows = query_rows(
        conn,
        "SELECT et.epic_id, et.task_num, et.title FROM epic_tasks et "
        "WHERE et.status = 'reviewing-implementation' "
        "AND NOT EXISTS ("
        "  SELECT 1 FROM qa_requirements qr WHERE qr.epic_id = et.epic_id AND qr.task_num = et.task_num"
        ") ORDER BY et.epic_id, et.task_num",
    )
    for row in task_rows:
        issues.append(
            f"- Epic {row['epic_id']}/task {row['task_num']}: '{row['title']}' "
            f"— in reviewing-implementation with zero qa_requirements"
        )

    if issues:
        rec.record("HC-validation-no-qa-reqs",
                    "Items in reviewing-implementation without QA requirements", "WARN",
                    "\n".join(issues))
    else:
        rec.record("HC-validation-no-qa-reqs",
                    "Items in reviewing-implementation without QA requirements", "PASS", "")



def hc_smoke_failure_stale(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-smoke-failure-stale: Stale smoke QA requirements."""
    if not _base._table_exists(conn, "qa_requirements"):
        rec.record("HC-smoke-failure-stale", "Stale smoke QA requirements", "PASS",
                    "qa_requirements table does not exist yet — skipping")
        return

    issues: List[str] = []
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    rows = query_rows(
        conn,
        "SELECT qr.id, qr.deployment_run_id, qr.created_at "
        "FROM qa_requirements qr "
        "WHERE qr.qa_kind = 'smoke' AND qr.qa_phase = 'post_deploy' "
        "AND qr.waived_at IS NULL "
        f"AND qr.created_at < {_p(conn)} "
        "AND NOT EXISTS ("
        "  SELECT 1 FROM qa_runs qrun WHERE qrun.qa_requirement_id = qr.id AND qrun.verdict = 'pass'"
        ") ORDER BY qr.created_at ASC",
        (cutoff,),
    )
    for row in rows:
        issues.append(
            f"- Requirement {row['id']} (run={row['deployment_run_id']}) "
            f"— smoke pending for {age_hours_since(row['created_at'])}h"
        )

    if issues:
        rec.record("HC-smoke-failure-stale", "Stale smoke QA requirements", "WARN",
                    "\n".join(issues))
    else:
        rec.record("HC-smoke-failure-stale", "Stale smoke QA requirements", "PASS", "")



def hc_smoke_artifact_orphan(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-smoke-artifact-orphan: Orphaned QA artifacts."""
    if not _base._table_exists(conn, "qa_artifacts"):
        rec.record("HC-smoke-artifact-orphan", "Orphaned QA artifacts", "PASS",
                    "qa_artifacts table does not exist yet — skipping")
        return

    issues: List[str] = []
    rows = query_rows(
        conn,
        "SELECT a.id, a.qa_run_id, a.artifact_type FROM qa_artifacts a "
        "WHERE NOT EXISTS (SELECT 1 FROM qa_runs qr WHERE qr.id = a.qa_run_id) "
        "UNION ALL "
        "SELECT a.id, a.qa_run_id, a.artifact_type FROM qa_artifacts a "
        "JOIN qa_runs qr ON qr.id = a.qa_run_id "
        "WHERE NOT EXISTS (SELECT 1 FROM qa_requirements req WHERE req.id = qr.qa_requirement_id) "
        "ORDER BY 1",
    )
    for row in rows:
        issues.append(
            f"- Artifact {row['id']} (run={row['qa_run_id']}, type={row['artifact_type']}) "
            f"— orphaned reference chain"
        )

    if issues:
        rec.record("HC-smoke-artifact-orphan", "Orphaned QA artifacts", "WARN",
                    "\n".join(issues))
    else:
        rec.record("HC-smoke-artifact-orphan", "Orphaned QA artifacts", "PASS", "")


__all__ = (
    "hc_run_qa_unsatisfied",
    "hc_validation_no_qa_reqs",
    "hc_smoke_failure_stale",
    "hc_smoke_artifact_orphan",
)
