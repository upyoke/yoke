"""Database health checks — deployment flows and ephemeral environments.

HC functions covering deploy-stage integrity, deployment-flow validity, and
ephemeral environment lifecycle:
- ``hc_preview_occupancy_stale`` — preview envs claimed by inactive runs.
- ``hc_orphaned_ephemeral`` — done items with non-stopped ephemeral envs.
- ``hc_deploy_stage_integrity`` — deploy_stage=complete without evidence.
- ``hc_incomplete_deploy_stage`` — done items with incomplete deploy_stage.
- ``hc_flow_workflow_exists`` — flow stage workflow files exist in project repos.
- ``hc_zombie_ephemeral_envs`` — ephemeral envs stuck non-terminal too long.
"""

from __future__ import annotations

from yoke_core.domain.workflow_status_queries import completed_items_sql
from yoke_core.domain.workflow_runtime import load_item_workflow_runtime

from typing import List

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import query_rows, query_scalar
from yoke_core.domain.project_identity import render_item_ref
from yoke_core.domain.item_ref_resolution import resolve_item_ref_or_none
from yoke_core.domain.time_parse import age_hours_since
from yoke_core.domain.time_sql import now_sql

import yoke_core.engines.doctor_report as _base

from yoke_core.engines.doctor_report import (
    DoctorArgs,
    RecordCollector,
)


from yoke_core.engines.doctor_hc_db_flow_workflows import hc_flow_workflow_exists  # noqa: F401
from yoke_core.engines.doctor_hc_db_flow_environment_inputs import (  # noqa: F401
    hc_flow_stage_environment_input,
)


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def hc_preview_occupancy_stale(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-preview-occupancy-stale: Preview environments claimed by inactive runs."""
    if not _base._table_exists(conn, "deployment_preview_environments"):
        rec.record(
            "HC-preview-occupancy-stale",
            "Preview environments claimed by inactive runs",
            "PASS",
            "deployment_preview_environments table does not exist — skipping",
        )
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
        rec.record(
            "HC-preview-occupancy-stale",
            "Preview environments claimed by inactive runs",
            "WARN",
            "\n".join(issues),
        )
    else:
        rec.record(
            "HC-preview-occupancy-stale",
            "Preview environments claimed by inactive runs",
            "PASS",
            "",
        )


def hc_orphaned_ephemeral(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-orphaned-ephemeral: Items at done with non-stopped ephemeral envs."""
    if not _base._table_exists(conn, "ephemeral_environments"):
        rec.record(
            "HC-orphaned-ephemeral",
            "Orphaned ephemeral environments",
            "PASS",
            "ephemeral_environments table does not exist — skipping",
        )
        return

    issues: List[str] = []
    # ``ephemeral_environments.item`` holds a public ref whose prefix belongs to
    # the owning project, so the item is resolved through the ref parser rather
    # than matched against a prefix built in SQL.
    env_rows = query_rows(
        conn,
        "SELECT id as ee_id, item as ee_item, status as ee_status "
        "FROM ephemeral_environments "
        "WHERE status <> 'stopped' AND item IS NOT NULL AND item <> '' "
        "ORDER BY id",
    )
    for env in env_rows:
        item_id = resolve_item_ref_or_none(conn, str(env["ee_item"]))
        if item_id is None:
            continue
        status = query_scalar(
            conn,
            f"SELECT status FROM items WHERE id = {_p(conn)}",
            (int(item_id),),
        )
        if (
            str(status)
            not in load_item_workflow_runtime(conn, int(item_id)).terminal_stage_ids
        ):
            continue
        issues.append(
            f"- {render_item_ref(conn, int(item_id))}: ephemeral env "
            f"'{env['ee_id']}' still at status='{env['ee_status']}' "
            "(expected stopped)"
        )

    if issues:
        rec.record(
            "HC-orphaned-ephemeral",
            "Orphaned ephemeral environments",
            "WARN",
            "\n".join(issues),
        )
    else:
        rec.record(
            "HC-orphaned-ephemeral", "Orphaned ephemeral environments", "PASS", ""
        )


def hc_deploy_stage_integrity(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-deploy-stage-integrity: deploy_stage=complete without deployment evidence."""
    if not _base._column_exists(conn, "items", "deploy_stage"):
        rec.record(
            "HC-deploy-stage-integrity",
            "deploy_stage without deployment evidence",
            "PASS",
            "deploy_stage column does not exist yet — skipping",
        )
        return

    if not _base._table_exists(conn, "deployment_runs"):
        count = query_scalar(
            conn, "SELECT count(*) FROM items WHERE deploy_stage = 'complete'"
        )
        if count and int(count) > 0:
            rec.record(
                "HC-deploy-stage-integrity",
                "deploy_stage without deployment evidence",
                "WARN",
                f"{count} item(s) have deploy_stage=complete but deployment_runs table does not exist",
            )
        else:
            rec.record(
                "HC-deploy-stage-integrity",
                "deploy_stage without deployment evidence",
                "PASS",
                "",
            )
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
        f"- {render_item_ref(conn, r['id'])}: deploy_stage='complete' with deployment_flow='{r['deployment_flow'] or 'null'}' "
        f"but 0 deployment evidence"
        for r in rows
    ]

    if issues:
        rec.record(
            "HC-deploy-stage-integrity",
            "deploy_stage without deployment evidence",
            "WARN",
            "\n".join(issues),
        )
    else:
        rec.record(
            "HC-deploy-stage-integrity",
            "deploy_stage without deployment evidence",
            "PASS",
            "",
        )


def hc_incomplete_deploy_stage(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-incomplete-deploy-stage: Done items with incomplete deploy_stage."""
    if not _base._column_exists(conn, "items", "deploy_stage"):
        rec.record(
            "HC-incomplete-deploy-stage",
            "Done items with incomplete deploy_stage",
            "PASS",
            "deploy_stage column does not exist yet — skipping",
        )
        return

    has_runs = _base._table_exists(conn, "deployment_runs")
    if has_runs:
        rows = query_rows(
            conn,
            "SELECT i.id, i.deployment_flow, i.deploy_stage FROM items i "
            f"WHERE {completed_items_sql(conn)} "
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
            f"WHERE {completed_items_sql(conn)} "
            "AND i.deployment_flow IS NOT NULL AND i.deployment_flow <> '' "
            "AND (i.deploy_stage IS NULL OR i.deploy_stage <> 'complete') "
            "ORDER BY i.id",
        )

    _cut = _base._read_int_cutoff("hc_incomplete_deploy_stage_min_item_id")
    issues = [
        f"- {render_item_ref(conn, r['id'])}: deployment_flow='{r['deployment_flow']}' "
        f"but deploy_stage='{r['deploy_stage'] or 'null'}'"
        for r in rows
        if _cut is None or r["id"] >= _cut
    ]

    if issues:
        rec.record(
            "HC-incomplete-deploy-stage",
            "Done items with incomplete deploy_stage",
            "WARN",
            "\n".join(issues),
        )
    else:
        rec.record(
            "HC-incomplete-deploy-stage",
            "Done items with incomplete deploy_stage",
            "PASS",
            "",
        )


def hc_zombie_ephemeral_envs(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-zombie-ephemeral-envs: Zombie ephemeral environments."""
    if not _base._table_exists(conn, "ephemeral_environments"):
        rec.record(
            "HC-zombie-ephemeral-envs",
            "Zombie ephemeral environments",
            "PASS",
            "ephemeral_environments table does not exist yet — skipping",
        )
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
        rec.record(
            "HC-zombie-ephemeral-envs",
            "Zombie ephemeral environments",
            "WARN",
            "\n".join(issues),
        )
    else:
        rec.record(
            "HC-zombie-ephemeral-envs", "Zombie ephemeral environments", "PASS", ""
        )


__all__ = (
    "hc_preview_occupancy_stale",
    "hc_orphaned_ephemeral",
    "hc_deploy_stage_integrity",
    "hc_incomplete_deploy_stage",
    "hc_flow_workflow_exists",
    "hc_flow_stage_environment_input",
    "hc_zombie_ephemeral_envs",
)
