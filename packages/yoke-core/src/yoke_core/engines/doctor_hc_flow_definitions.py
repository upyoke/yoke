"""Database health checks for deployment flow definitions and references."""

from __future__ import annotations

from typing import List
from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.project_identity import render_item_ref
from yoke_core.domain.sql_json import json_valid_expr
import yoke_core.engines.doctor_report as _base
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


def hc_flow_stage_json(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-flow-stage-json: Deployment flow stage JSON validity."""
    if not _base._table_exists(conn, "deployment_flows"):
        rec.record(
            "HC-flow-stage-json",
            "Deployment flow stage JSON validity",
            "PASS",
            "deployment_flows table does not exist yet — skipping",
        )
        return

    rows = query_rows(
        conn,
        # Native Postgres ``IS JSON`` predicate (true for valid JSON); the
        # invalid-rows filter negates it (``NOT`` not ``= 0`` — PG type error).
        f"SELECT id, stages FROM deployment_flows WHERE NOT {json_valid_expr('stages')} ORDER BY id",
    )
    issues = [f"- flow '{r['id']}': stages field contains invalid JSON" for r in rows]

    if issues:
        rec.record(
            "HC-flow-stage-json",
            "Deployment flow stage JSON validity",
            "FAIL",
            "\n".join(issues),
        )
    else:
        rec.record(
            "HC-flow-stage-json", "Deployment flow stage JSON validity", "PASS", ""
        )


def hc_invalid_item_flows(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-invalid-item-flows: items referencing non-existent or cross-project deployment flows.

    Non-existent rows surface the registered alternatives (filtered by the
    item's project when set) so the operator can repair the row directly.
    No --fix path: ``deployment_flow`` carries operator intent and cannot
    be auto-inferred.
    """
    if not _base._table_exists(conn, "deployment_flows"):
        rec.record(
            "HC-invalid-item-flows",
            "Items referencing non-existent or cross-project deployment flows",
            "PASS",
            "",
        )
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
            f"- {render_item_ref(conn, r['id'])}: deployment_flow '{r['deployment_flow']}' "
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
            f"- {render_item_ref(conn, r['id'])}: project '{r['project']}' but deployment_flow "
            f"'{r['deployment_flow']}' belongs to project '{r['flow_project']}'"
        )

    if issues:
        rec.record(
            "HC-invalid-item-flows",
            "Items referencing non-existent or cross-project deployment flows",
            "WARN",
            "\n".join(issues),
        )
    else:
        rec.record(
            "HC-invalid-item-flows",
            "Items referencing non-existent or cross-project deployment flows",
            "PASS",
            "",
        )
