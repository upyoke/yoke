"""Approval-stage CLI commands.

Owns ``approve-check`` (validate that a deployment-flow stage is a
human-approval stage and surface the next stage) and ``apply-approval``
(prepare an approval mutation against the active deployment run).
Both delegate to the shared mutation/approval domain layer for the
business rules and only handle CLI argument parsing and JSON
serialisation here.
"""

from __future__ import annotations

import json
import sys

from yoke_core.api.service_client_shared import (
    _get_db_readonly,
    _load_item_state,
    _mutation_result_to_dict,
    approval,
    mutations,
    runs,
)


def cmd_approve_check(args: list[str]) -> int:
    """Validate approval for a flow stage and return the next stage.

    Usage: approve-check <flow-id> <current-stage>

    Reads the deployment flow's stages from the DB, validates that the
    current stage is a human-approval stage, and prints the next stage
    name to stdout on success.

    Exit 0: approval valid, next stage on stdout
    Exit 1: approval invalid, error on stderr
    """
    if len(args) < 2:
        print("Usage: approve-check <flow-id> <current-stage>", file=sys.stderr)
        return 2

    flow_id = args[0]
    current_stage = args[1]

    conn = _get_db_readonly()
    try:
        row = conn.execute(
            "SELECT stages FROM deployment_flows WHERE id = %s",
            (flow_id,),
        ).fetchone()
        if row is None:
            print(f"Error: deployment flow '{flow_id}' not found", file=sys.stderr)
            return 1

        stages = approval.parse_flow_stages(row["stages"])
        resolution = approval.resolve_approval(stages, current_stage)

        if not resolution.approved:
            print(f"Error: {resolution.error}", file=sys.stderr)
            return 1

        result = {
            "approved": True,
            "next_stage": resolution.next_stage,
            "current_stage": current_stage,
            "flow_id": flow_id,
        }
        print(json.dumps(result))
        return 0
    finally:
        conn.close()


def cmd_apply_approval(args: list[str]) -> int:
    """Validate and prepare an approval-apply mutation via the shared mutation layer.

    Usage: apply-approval <item-id>

    Reads the item's deployment flow, resolves the active run, and returns
    the approval result as JSON on stdout.

    Exit 0: valid, JSON result on stdout
    Exit 1: validation/state error, JSON error on stdout
    """
    if len(args) < 1:
        print("Usage: apply-approval <item-id>", file=sys.stderr)
        return 2

    try:
        item_id = int(args[0])
    except ValueError:
        print(json.dumps({
            "success": False,
            "error": f"Item ID must be an integer, got '{args[0]}'",
            "error_code": "VALIDATION_ERROR",
        }))
        return 1

    conn = _get_db_readonly()
    try:
        item_state = _load_item_state(conn, item_id)
        if item_state is None:
            print(json.dumps({
                "success": False,
                "error": f"Item YOK-{item_id} not found",
                "error_code": "NOT_FOUND",
            }))
            return 1

        flow_stages = []
        if item_state.deployment_flow:
            flow_row = conn.execute(
                "SELECT stages FROM deployment_flows WHERE id = %s",
                (item_state.deployment_flow,),
            ).fetchone()
            if flow_row:
                flow_stages = approval.parse_flow_stages(flow_row["stages"])

        run_rows = conn.execute(
            """SELECT dr.*, p.slug AS project FROM deployment_run_items dri
               JOIN deployment_runs dr ON dr.id = dri.run_id
               JOIN projects p ON p.id = dr.project_id
               WHERE dri.item_id = %s
               ORDER BY dr.created_at DESC""",
            (item_id,),
        ).fetchall()

        active_run = runs.find_active_run_for_item([
            runs.DeploymentRun(
                id=r["id"],
                project=r["project"],
                flow=r["flow"],
                status=r["status"],
                current_stage=r["current_stage"],
                created_at=r["created_at"],
            )
            for r in run_rows
        ])

        member_item_ids = []
        if active_run:
            member_rows = conn.execute(
                "SELECT item_id FROM deployment_run_items WHERE run_id = %s",
                (active_run.id,),
            ).fetchall()
            member_item_ids = [m["item_id"] for m in member_rows]

        result = mutations.prepare_approval(
            item=item_state,
            flow_stages=flow_stages,
            active_run=active_run,
            member_item_ids=member_item_ids,
        )

        print(json.dumps(_mutation_result_to_dict(result)))
        return 0 if result.success else 1
    finally:
        conn.close()
