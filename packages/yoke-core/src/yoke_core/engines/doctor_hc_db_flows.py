"""Database health checks — deployment flows and ephemeral environments.

HC functions covering deploy-stage integrity, deployment-flow validity, and
ephemeral environment lifecycle:
- ``hc_preview_occupancy_stale`` — preview envs claimed by inactive runs.
- ``hc_orphaned_ephemeral`` — done items with non-stopped ephemeral envs.
- ``hc_deploy_stage_integrity`` — deploy_stage=complete without evidence.
- ``hc_incomplete_deploy_stage`` — done items with incomplete deploy_stage.
- ``hc_flow_stage_json`` — deployment_flows.stages JSON validity.
- ``hc_flow_workflow_exists`` — flow stage workflow files exist in project repos.
- ``hc_invalid_item_flows`` — items referencing missing/cross-project flows.
- ``hc_zombie_ephemeral_envs`` — ephemeral envs stuck non-terminal too long.
"""

from __future__ import annotations

import json
from typing import List

from yoke_core.domain.db_helpers import query_rows, query_scalar
from yoke_core.domain.time_parse import age_hours_since
from yoke_core.domain.time_sql import now_sql
from yoke_core.domain.sql_json import json_valid_expr

import yoke_core.engines.doctor_report as _base

from yoke_core.engines.doctor_report import (
    DoctorArgs,
    RecordCollector,
)
from yoke_core.engines.doctor_hc_db_flow_workflows import hc_flow_workflow_exists  # noqa: F401
from yoke_core.engines.doctor_hc_db_flows_migration_coverage import hc_project_flow_migration_apply_coverage  # noqa: F401


def hc_preview_occupancy_stale(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-preview-occupancy-stale: Preview environments claimed by inactive runs."""
    if not _base._table_exists(conn, "deployment_preview_environments"):
        rec.record("HC-preview-occupancy-stale",
                    "Preview environments claimed by inactive runs", "PASS",
                    "deployment_preview_environments table does not exist — skipping")
        return

    issues: List[str] = []
    rows = query_rows(
        conn,
        "SELECT COALESCE(p.slug, CAST(pe.project_id AS TEXT)) AS project, "
        "pe.env_name, pe.run_id, dr.status "
        "FROM deployment_preview_environments pe "
        "LEFT JOIN projects p ON p.id = pe.project_id "
        "JOIN deployment_runs dr ON dr.id = pe.run_id "
        "WHERE pe.status = 'claimed' "
        "AND dr.status IN ('succeeded', 'failed', 'cancelled') "
        "ORDER BY project, pe.env_name",
    )
    for row in rows:
        issues.append(
            f"- {row['project']}/{row['env_name']}: claimed by run '{row['run_id']}' "
            f"(status={row['status']}) — should be released"
        )

    if issues:
        rec.record("HC-preview-occupancy-stale",
                    "Preview environments claimed by inactive runs", "WARN",
                    "\n".join(issues))
    else:
        rec.record("HC-preview-occupancy-stale",
                    "Preview environments claimed by inactive runs", "PASS", "")



def hc_orphaned_ephemeral(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-orphaned-ephemeral: Items at done with non-stopped ephemeral envs."""
    if not _base._table_exists(conn, "ephemeral_environments"):
        rec.record("HC-orphaned-ephemeral", "Orphaned ephemeral environments", "PASS",
                    "ephemeral_environments table does not exist — skipping")
        return

    issues: List[str] = []
    rows = query_rows(
        conn,
        "SELECT i.id, ee.id as ee_id, ee.status as ee_status FROM items i "
        "JOIN ephemeral_environments ee ON ee.item = 'YOK-' || i.id "
        "WHERE i.status = 'done' AND ee.status <> 'stopped' "
        "ORDER BY i.id",
    )
    for row in rows:
        issues.append(
            f"- YOK-{row['id']}: ephemeral env '{row['ee_id']}' still at "
            f"status='{row['ee_status']}' (expected stopped)"
        )

    if issues:
        rec.record("HC-orphaned-ephemeral", "Orphaned ephemeral environments", "WARN",
                    "\n".join(issues))
    else:
        rec.record("HC-orphaned-ephemeral", "Orphaned ephemeral environments", "PASS", "")



def hc_deploy_stage_integrity(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-deploy-stage-integrity: deploy_stage=complete without deployment evidence."""
    if not _base._column_exists(conn, "items", "deploy_stage"):
        rec.record("HC-deploy-stage-integrity", "deploy_stage without deployment evidence", "PASS",
                    "deploy_stage column does not exist yet — skipping")
        return

    if not _base._table_exists(conn, "deployment_runs"):
        count = query_scalar(conn,
                             "SELECT count(*) FROM items WHERE deploy_stage = 'complete'")
        if count and int(count) > 0:
            rec.record("HC-deploy-stage-integrity", "deploy_stage without deployment evidence", "WARN",
                        f"{count} item(s) have deploy_stage=complete but deployment_runs table does not exist")
        else:
            rec.record("HC-deploy-stage-integrity", "deploy_stage without deployment evidence", "PASS", "")
        return

    rows = query_rows(
        conn,
        "SELECT i.id, i.deployment_flow, i.deploy_stage FROM items i "
        "WHERE i.deploy_stage = 'complete' "
        "AND i.created_at >= '2026-03-16' "
        "AND NOT EXISTS ("
        "  SELECT 1 FROM deployment_run_items dri WHERE dri.item_id = i.id"
        ") ORDER BY i.id",
    )

    issues = [
        f"- YOK-{r['id']}: deploy_stage='complete' with deployment_flow='{r['deployment_flow'] or 'null'}' "
        f"but 0 deployment evidence"
        for r in rows
    ]

    if issues:
        rec.record("HC-deploy-stage-integrity", "deploy_stage without deployment evidence", "WARN",
                    "\n".join(issues))
    else:
        rec.record("HC-deploy-stage-integrity", "deploy_stage without deployment evidence", "PASS", "")



def hc_incomplete_deploy_stage(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-incomplete-deploy-stage: Done items with incomplete deploy_stage."""
    if not _base._column_exists(conn, "items", "deploy_stage"):
        rec.record("HC-incomplete-deploy-stage", "Done items with incomplete deploy_stage", "PASS",
                    "deploy_stage column does not exist yet — skipping")
        return

    has_runs = _base._table_exists(conn, "deployment_runs")
    if has_runs:
        rows = query_rows(
            conn,
            "SELECT i.id, i.deployment_flow, i.deploy_stage FROM items i "
            "WHERE i.status = 'done' "
            "AND i.deployment_flow IS NOT NULL AND i.deployment_flow <> '' "
            "AND (i.deploy_stage IS NULL OR i.deploy_stage <> 'complete') "
            "AND NOT EXISTS ("
            "  SELECT 1 FROM deployment_run_items dri "
            "  JOIN deployment_runs dr ON dr.id = dri.run_id "
            "  WHERE dri.item_id = i.id AND dr.status = 'succeeded'"
            ") ORDER BY i.id",
        )
    else:
        rows = query_rows(
            conn,
            "SELECT i.id, i.deployment_flow, i.deploy_stage FROM items i "
            "WHERE i.status = 'done' "
            "AND i.deployment_flow IS NOT NULL AND i.deployment_flow <> '' "
            "AND (i.deploy_stage IS NULL OR i.deploy_stage <> 'complete') "
            "ORDER BY i.id",
        )

    _cut = _base._read_int_cutoff("hc_incomplete_deploy_stage_min_item_id")
    issues = [
        f"- YOK-{r['id']}: deployment_flow='{r['deployment_flow']}' "
        f"but deploy_stage='{r['deploy_stage'] or 'null'}'"
        for r in rows if _cut is None or r['id'] >= _cut
    ]

    if issues:
        rec.record("HC-incomplete-deploy-stage", "Done items with incomplete deploy_stage", "WARN",
                    "\n".join(issues))
    else:
        rec.record("HC-incomplete-deploy-stage", "Done items with incomplete deploy_stage", "PASS", "")



def hc_flow_stage_json(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-flow-stage-json: Deployment flow stage JSON validity."""
    if not _base._table_exists(conn, "deployment_flows"):
        rec.record("HC-flow-stage-json", "Deployment flow stage JSON validity", "PASS",
                    "deployment_flows table does not exist yet — skipping")
        return

    rows = query_rows(
        conn,
        # Native Postgres ``IS JSON`` predicate (true for valid JSON); the
        # invalid-rows filter negates it (``NOT`` not ``= 0`` — PG type error).
        f"SELECT id, stages FROM deployment_flows WHERE NOT {json_valid_expr('stages')} ORDER BY id",
    )
    issues = [f"- flow '{r['id']}': stages field contains invalid JSON" for r in rows]

    if issues:
        rec.record("HC-flow-stage-json", "Deployment flow stage JSON validity", "FAIL", "\n".join(issues))
    else:
        rec.record("HC-flow-stage-json", "Deployment flow stage JSON validity", "PASS", "")



def hc_invalid_item_flows(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-invalid-item-flows: items referencing non-existent or cross-project deployment flows.

    Non-existent rows surface the registered alternatives (filtered by the
    item's project when set) so the operator can repair the row directly.
    No --fix path: ``deployment_flow`` carries operator intent and cannot
    be auto-inferred.
    """
    if not _base._table_exists(conn, "deployment_flows"):
        rec.record("HC-invalid-item-flows",
                    "Items referencing non-existent or cross-project deployment flows", "PASS", "")
        return

    from yoke_core.domain.deployment_flow_validator import list_registered_flow_ids

    all_flows = list_registered_flow_ids(conn)
    issues: List[str] = []
    rows = query_rows(
        conn,
        "SELECT i.id, p.slug AS project, i.deployment_flow FROM items i "
        "LEFT JOIN projects p ON p.id = i.project_id "
        "WHERE i.deployment_flow IS NOT NULL AND i.deployment_flow <> '' "
        "AND NOT EXISTS (SELECT 1 FROM deployment_flows df WHERE df.id = i.deployment_flow) "
        "ORDER BY i.id",
    )
    for r in rows:
        item_project = r["project"]
        if item_project:
            project_flows = list_registered_flow_ids(conn, item_project)
            if project_flows:
                alt_label = f"registered for project '{item_project}'"
                alts = project_flows
            else:
                alt_label = f"registered (no flows for project '{item_project}')"
                alts = all_flows
        else:
            alt_label = "registered"
            alts = all_flows
        alts_str = ", ".join(alts) if alts else "(none registered)"
        issues.append(
            f"- YOK-{r['id']}: deployment_flow '{r['deployment_flow']}' "
            f"is not registered. {alt_label}: {alts_str}. "
            f"--fix cannot infer operator intent; repair by hand."
        )

    rows2 = query_rows(
        conn,
        "SELECT i.id, ip.slug AS project, i.deployment_flow, fp.slug as flow_project "
        "FROM items i JOIN deployment_flows df ON df.id = i.deployment_flow "
        "LEFT JOIN projects ip ON ip.id = i.project_id "
        "LEFT JOIN projects fp ON fp.id = df.project_id "
        "WHERE i.deployment_flow IS NOT NULL AND i.deployment_flow <> '' "
        "AND i.project_id IS NOT NULL "
        "AND df.project_id IS NOT NULL "
        "AND i.project_id <> df.project_id ORDER BY i.id",
    )
    for r in rows2:
        issues.append(
            f"- YOK-{r['id']}: project '{r['project']}' but deployment_flow "
            f"'{r['deployment_flow']}' belongs to project '{r['flow_project']}'"
        )

    if issues:
        rec.record("HC-invalid-item-flows",
                    "Items referencing non-existent or cross-project deployment flows", "WARN",
                    "\n".join(issues))
    else:
        rec.record("HC-invalid-item-flows",
                    "Items referencing non-existent or cross-project deployment flows", "PASS", "")



def hc_zombie_ephemeral_envs(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-zombie-ephemeral-envs: Zombie ephemeral environments."""
    if not _base._table_exists(conn, "ephemeral_environments"):
        rec.record("HC-zombie-ephemeral-envs", "Zombie ephemeral environments", "PASS",
                    "ephemeral_environments table does not exist yet — skipping")
        return

    rows = query_rows(
        conn,
        "SELECT ee.id, COALESCE(p.slug, CAST(ee.project_id AS TEXT)) AS project, "
        "ee.branch, ee.status, ee.created_at "
        "FROM ephemeral_environments ee "
        "LEFT JOIN projects p ON p.id = ee.project_id "
        "WHERE ee.status IN ('pending', 'starting', 'running', 'healthy') "
        f"AND ee.created_at < {now_sql(offset_hours=-4)} ORDER BY ee.id",
    )

    issues = [
        f"- env {r['id']} (project='{r['project']}', branch='{r['branch']}'): "
        f"status '{r['status']}' for {age_hours_since(r['created_at'])}h "
        f"(since {r['created_at']})"
        for r in rows
    ]

    if issues:
        rec.record("HC-zombie-ephemeral-envs", "Zombie ephemeral environments", "WARN",
                    "\n".join(issues))
    else:
        rec.record("HC-zombie-ephemeral-envs", "Zombie ephemeral environments", "PASS", "")


__all__ = (
    "hc_preview_occupancy_stale", "hc_orphaned_ephemeral",
    "hc_deploy_stage_integrity", "hc_incomplete_deploy_stage",
    "hc_flow_stage_json", "hc_flow_workflow_exists",
    "hc_invalid_item_flows", "hc_zombie_ephemeral_envs",
)
