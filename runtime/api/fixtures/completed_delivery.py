"""Pin delivery fixture runs to registered environments and exact candidates."""

import json
from typing import Any

from runtime.api.domain.test_deployment_qa_stage_execution import _environment
from runtime.api.fixtures.deployment_run_driver_fixture import attach_seeded_driver
from yoke_core.domain.deployment_flow_versioning import cmd_create
from yoke_core.domain.deployment_stage_receipts import (
    allocate_deployment_stage_receipt,
    complete_deployment_stage_receipt,
)
from yoke_core.domain.deployment_requirement_snapshots import (
    requirement_selection,
    snapshot_flow_requirements,
    snapshot_member_requirements,
)


def pin_run_delivery(conn, run_id, *, environment=None, candidate=None):
    row = conn.execute(
        "SELECT dr.project_id,dr.release_lineage,e.name FROM deployment_runs dr "
        "LEFT JOIN deployment_flows f ON f.id=dr.flow "
        "LEFT JOIN environments e ON e.id=f.target_environment_id WHERE dr.id=%s",
        (run_id,),
    ).fetchone()
    project_id = int(row[0])
    environment = environment or row[2] or "prod"
    conn.execute(
        "INSERT INTO environments(site,project_id,name,url,created_at) "
        "SELECT id,%s,%s,%s,'2026-10-01T00:00:00Z' FROM sites "
        "WHERE project_id=%s ORDER BY id LIMIT 1 "
        "ON CONFLICT(project_id,name) DO NOTHING",
        (project_id, environment, f"https://{environment}.example.test", project_id),
    )
    conn.execute(
        "UPDATE deployment_runs SET target_tier='persistent', "
        "target_environment_id=(SELECT id FROM environments WHERE project_id=%s AND name=%s), "
        "release_lineage=%s WHERE id=%s",
        (project_id, environment, candidate or row[1] or "a" * 40, run_id),
    )


def _stage(environment: str = "stage") -> dict[str, Any]:
    return {
        "name": "member-qa",
        "step_runner": "qa",
        "stage_kind": "qa",
        "scope": "item",
        "target": {
            "kind": "persistent_environment",
            "environment": environment,
            "source_stage": "deploy",
        },
        "verdict": {"mode": "agent_only"},
    }


def seed_selected_requirement_run(
    conn: Any,
    *,
    run_id: str,
    item_id: int,
    requirement_id: int,
    environment: str = "stage",
) -> None:
    _environment(conn)
    if environment != "stage":
        conn.execute(
            "INSERT INTO environments(site,project_id,name,url,settings,created_at) "
            "SELECT id,1,%s,%s,'{}',%s FROM sites WHERE project_id=1 "
            "ORDER BY id LIMIT 1 ON CONFLICT(project_id,name) DO NOTHING",
            (
                environment,
                f"https://{environment}.example.test",
                "2026-09-14T00:00:00Z",
            ),
        )
    stages = [
        {
            "name": "deploy",
            "step_runner": "auto",
            "stage_kind": "execution",
            "scope": "run",
        },
        _stage(environment),
    ]
    flow_id = f"flow-{run_id}"
    cmd_create(
        conn,
        flow_id,
        "yoke",
        flow_id,
        "",
        json.dumps(stages),
        status="disabled",
    )
    flow_snapshot = snapshot_flow_requirements(
        conn, flow_id=flow_id, project_id=1, stages=stages
    )
    conn.execute(
        "INSERT INTO deployment_runs("
        "id,project_id,flow,release_lineage,status,current_stage,created_at,"
        "composition_frozen_at,requirement_snapshot"
        ") VALUES (%s,1,%s,%s,'executing','deploy',%s,%s,%s)",
        (
            run_id,
            flow_id,
            "c" * 40,
            "2026-09-14T00:00:00Z",
            "2026-09-14T00:01:00Z",
            flow_snapshot,
        ),
    )
    pin_run_delivery(conn, run_id, environment=environment)
    member_snapshot = snapshot_member_requirements(
        conn,
        run_id=run_id,
        item_id=item_id,
        selection_json=requirement_selection(requirement_ids=(requirement_id,)),
    )
    conn.execute(
        "INSERT INTO deployment_run_items(run_id,item_id,added_at,requirement_snapshot) "
        "VALUES (%s,%s,%s,%s)",
        (run_id, item_id, "2026-09-14T00:00:00Z", member_snapshot),
    )
    conn.execute(
        "UPDATE items SET deployment_flow = %s WHERE id = %s",
        (flow_id, item_id),
    )
    receipt = allocate_deployment_stage_receipt(
        conn,
        run_id=run_id,
        stage_name="deploy",
        correlation_id=f"{run_id}-deploy-1",
        target_kind="persistent_environment",
        executor="test",
        commit=False,
    )
    complete_deployment_stage_receipt(
        conn,
        run_id=run_id,
        receipt_id=int(receipt["id"]),
        correlation_id=str(receipt["correlation_id"]),
        status="ready",
        target_name=environment,
        observed_url=f"https://{environment}.example.test"
        if environment != "stage"
        else "https://preview.example.test",
        observed_release_lineage="c" * 40,
        executor_receipt="test://deploy-ready",
        commit=False,
    )
    conn.execute(
        "UPDATE deployment_runs SET current_stage='member-qa' WHERE id=%s",
        (run_id,),
    )
    attach_seeded_driver(conn, run_id)
    conn.commit()
