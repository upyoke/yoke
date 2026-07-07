"""Database health checks — deployment-run integrity (core).

Core run-integrity HC functions covering orphaned FK references and
deployment-run state. QA-related HCs and deploy-flow HCs live in focused
sibling modules:

- ``doctor_hc_db_qa`` — QA requirements, smoke artifacts, validation gating.
- ``doctor_hc_db_flows`` — deploy-stage integrity, deployment flow validity,
  ephemeral environment lifecycle.
- ``doctor_hc_db_project`` — project FK integrity and configuration validity;
  re-exports orphan-reference and schema-drift HCs from focused siblings
  ``doctor_hc_db_project_orphans`` and ``doctor_hc_db_project_schema``.
- ``doctor_hc_db_events_{ledger,registry,emission}`` — event-ledger trust,
  registry coverage, emission rate plus stray-DB detection.
- ``doctor_hc_db_catalog`` — event catalog drift, callsite registry sync.

This module remains the canonical entry point that ``doctor.py`` imports.
It defines the four core run-integrity HCs and re-exports the public HC
functions owned by ``doctor_hc_db_qa`` and ``doctor_hc_db_flows`` so the
``doctor.py`` registration block keeps a single import statement.
"""

from __future__ import annotations

from typing import List

from yoke_core.domain.db_helpers import query_rows, query_scalar
from yoke_core.domain.time_sql import now_sql

import yoke_core.engines.doctor_report as _base

from yoke_core.engines.doctor_report import (
    DoctorArgs,
    RecordCollector,
)

from yoke_core.engines.doctor_hc_db_qa import (
    hc_run_qa_unsatisfied,
    hc_smoke_artifact_orphan,
    hc_smoke_failure_stale,
    hc_validation_no_qa_reqs,
)
from yoke_core.engines.doctor_hc_db_flows import (
    hc_deploy_stage_integrity,
    hc_flow_stage_json,
    hc_flow_workflow_exists,
    hc_incomplete_deploy_stage,
    hc_invalid_item_flows,
    hc_orphaned_ephemeral,
    hc_preview_occupancy_stale,
    hc_project_flow_migration_apply_coverage,
    hc_zombie_ephemeral_envs,
)


def hc_orphan_fk(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-orphan-fk: Orphaned FK references in shepherd child tables.

    Postgres (Yoke's control-plane authority) enforces declared FK
    constraints at write time — there is no per-connection enforcement
    toggle to probe — so this HC scans for orphaned rows that would
    reveal a missing or unenforced constraint rather than inspecting a
    SQLite ``PRAGMA foreign_keys`` switch.
    """
    issues: List[str] = []
    total = 0

    # Check caveat_dispositions -> shepherd_verdicts
    if _base._table_exists(conn, "caveat_dispositions") and _base._table_exists(conn, "shepherd_verdicts"):
        cd = query_scalar(
            conn,
            "SELECT COUNT(*) FROM caveat_dispositions "
            "WHERE verdict_id NOT IN (SELECT id FROM shepherd_verdicts)",
        )
        if cd and int(cd) > 0:
            issues.append(f"- caveat_dispositions: {cd} rows reference non-existent shepherd_verdicts")
            total += int(cd)

    if issues:
        rec.record(
            "HC-orphan-fk", f"Orphaned FK references ({total} total)", "FAIL",
            "\n".join(issues),
        )
    else:
        rec.record("HC-orphan-fk", "Orphaned FK references", "PASS",
                    "0 orphaned FK references")



def hc_orphaned_runs(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-orphaned-runs: item-less deployment runs abandoned before execution.

    Item-less runs that executed are legitimate environment-level deploys
    (stage/ephemeral bringup, operator redeploys); the orphan signal is a
    run created without items that never started executing.
    """
    if not _base._table_exists(conn, "deployment_runs"):
        rec.record("HC-orphaned-runs", "Item-less runs abandoned before execution", "PASS",
                    "deployment_runs table does not exist — skipping")
        return

    issues: List[str] = []
    rows = query_rows(
        conn,
        "SELECT dr.id, COALESCE(p.slug, CAST(dr.project_id AS TEXT)) AS project, "
        "dr.status, dr.created_at FROM deployment_runs dr "
        "LEFT JOIN projects p ON p.id = dr.project_id "
        "WHERE dr.status = 'created' AND NOT EXISTS ("
        "  SELECT 1 FROM deployment_run_items dri WHERE dri.run_id = dr.id"
        ") ORDER BY dr.created_at",
    )
    for row in rows:
        issues.append(
            f"- run '{row['id']}': project={row['project']}, "
            f"status={row['status']}, created={row['created_at']} — "
            "no member items and never started"
        )

    if issues:
        rec.record("HC-orphaned-runs", "Item-less runs abandoned before execution", "WARN",
                    "\n".join(issues))
    else:
        rec.record("HC-orphaned-runs", "Item-less runs abandoned before execution", "PASS", "")



def hc_stale_runs(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-stale-runs: Deployment runs stuck at executing for >24 hours."""
    if not _base._table_exists(conn, "deployment_runs"):
        rec.record("HC-stale-runs", "Deployment runs stuck at executing", "PASS",
                    "deployment_runs table does not exist — skipping")
        return

    issues: List[str] = []
    rows = query_rows(
        conn,
        "SELECT dr.id, COALESCE(p.slug, CAST(dr.project_id AS TEXT)) AS project, "
        "dr.current_stage, dr.started_at FROM deployment_runs dr "
        "LEFT JOIN projects p ON p.id = dr.project_id "
        "WHERE dr.status = 'executing' "
        "AND dr.started_at IS NOT NULL "
        f"AND dr.started_at < {now_sql(offset_hours=-24)} "
        "ORDER BY dr.started_at",
    )
    for row in rows:
        stage = row["current_stage"] or "unknown"
        issues.append(
            f"- run '{row['id']}': project={row['project']}, "
            f"stage={stage}, started={row['started_at']} — executing for >24h"
        )

    if issues:
        rec.record("HC-stale-runs", "Deployment runs stuck at executing", "WARN",
                    "\n".join(issues))
    else:
        rec.record("HC-stale-runs", "Deployment runs stuck at executing", "PASS", "")



def hc_run_item_status_consistency(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-run-item-status-consistency: Item/run status mismatches."""
    if not _base._table_exists(conn, "deployment_runs"):
        rec.record("HC-run-item-status-consistency", "Item/run status consistency", "PASS",
                    "deployment_runs table does not exist — skipping")
        return

    issues: List[str] = []

    # Check 1: Items at release not in any executing run
    rows = query_rows(
        conn,
        "SELECT i.id FROM items i "
        "WHERE i.status = 'release' "
        "AND NOT EXISTS ("
        "  SELECT 1 FROM deployment_run_items dri "
        "  JOIN deployment_runs dr ON dr.id = dri.run_id "
        "  WHERE dri.item_id = i.id AND dr.status = 'executing'"
        ") ORDER BY i.id",
    )
    for row in rows:
        issues.append(f"- YOK-{row['id']}: status=release but not in any executing run")

    # Check 2: Items at implemented in an executing run (should be release)
    rows2 = query_rows(
        conn,
        "SELECT i.id, dr.id as run_id FROM items i "
        "JOIN deployment_run_items dri ON dri.item_id = i.id "
        "JOIN deployment_runs dr ON dr.id = dri.run_id "
        "WHERE i.status = 'implemented' AND dr.status = 'executing' "
        "ORDER BY i.id",
    )
    for row in rows2:
        issues.append(
            f"- YOK-{row['id']}: status=implemented but in executing run '{row['run_id']}' (should be release)"
        )

    # Check 3: Items at done whose most recent run is not succeeded
    rows3 = query_rows(
        conn,
        "SELECT i.id, dr.id as run_id, dr.status as run_status FROM items i "
        "JOIN deployment_run_items dri ON dri.item_id = i.id "
        "JOIN deployment_runs dr ON dr.id = dri.run_id "
        "WHERE i.status = 'done' AND dr.status <> 'succeeded' "
        "AND NOT EXISTS ("
        "  SELECT 1 FROM deployment_run_items dri2 "
        "  JOIN deployment_runs dr2 ON dr2.id = dri2.run_id "
        "  WHERE dri2.item_id = i.id AND dr2.status = 'succeeded' "
        "  AND dr2.completed_at > COALESCE(dr.completed_at, dr.created_at)"
        ") ORDER BY i.id",
    )
    for row in rows3:
        issues.append(
            f"- YOK-{row['id']}: status=done but most recent run '{row['run_id']}' is '{row['run_status']}'"
        )

    if issues:
        rec.record("HC-run-item-status-consistency", "Item/run status consistency", "WARN",
                    "\n".join(issues))
    else:
        rec.record("HC-run-item-status-consistency", "Item/run status consistency", "PASS", "")


__all__ = (
    "hc_orphan_fk",
    "hc_orphaned_runs",
    "hc_stale_runs",
    "hc_run_item_status_consistency",
    # Re-exports from doctor_hc_db_qa
    "hc_run_qa_unsatisfied",
    "hc_validation_no_qa_reqs",
    "hc_smoke_failure_stale",
    "hc_smoke_artifact_orphan",
    # Re-exports from doctor_hc_db_flows
    "hc_preview_occupancy_stale",
    "hc_orphaned_ephemeral",
    "hc_deploy_stage_integrity",
    "hc_incomplete_deploy_stage",
    "hc_flow_stage_json",
    "hc_flow_workflow_exists",
    "hc_invalid_item_flows",
    "hc_zombie_ephemeral_envs",
)
