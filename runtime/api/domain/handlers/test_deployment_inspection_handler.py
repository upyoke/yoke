"""Handler coverage for deployment inventory and progress reads."""

from __future__ import annotations

import json

from runtime.api.deployment_stage_approval_fixture import gate_environment_id
from runtime.api.fixtures.backlog_inserts import insert_deployment_run
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers.deployment_inspection import (
    handle_deployment_flow_list,
    handle_deployment_run_stages,
    handle_deployment_runs_find_by_item,
)


def _request(function: str, target: TargetRef, payload: dict | None = None):
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(session_id="test-session"),
        target=target,
        payload=payload or {},
    )


def test_deployment_inspection_reads_existing_run(test_db) -> None:
    insert_deployment_run(
        test_db,
        id="run-inspect-001",
        project="yoke",
        flow="flow-inspect",
        status="executing",
        current_stage="deploy",
        target_environment_id=gate_environment_id(test_db),
        target_tier="persistent",
    )
    stages = [
        {"name": "build", "runner": "local_command"},
        {"name": "deploy", "runner": "local_command", "command": "build | deploy"},
        {"name": "verify", "runner": "local_command"},
    ]
    stored_stages = json.dumps(stages, indent=2)
    test_db.execute(
        "UPDATE deployment_flows SET stages=%s WHERE id=%s",
        (stored_stages, "flow-inspect"),
    )
    test_db.execute(
        "INSERT INTO deployment_run_items (run_id, item_id, added_at) "
        "VALUES (%s, %s, %s)",
        ("run-inspect-001", 711, "2026-08-05T12:00:00Z"),
    )
    test_db.commit()

    flows = handle_deployment_flow_list(
        _request(
            "deployment_flows.list",
            TargetRef(kind="global"),
            {"project": "yoke"},
        )
    )
    found = handle_deployment_runs_find_by_item(
        _request(
            "deployment_runs.find_by_item",
            TargetRef(kind="item", item_id=711),
        )
    )
    run_stages = handle_deployment_run_stages(
        _request(
            "deployment_runs.stages",
            TargetRef(kind="workflow_run", workflow_run_id="run-inspect-001"),
        )
    )

    assert flows.primary_success
    flow_rows = [
        row for row in flows.result_payload["rows"] if row["id"] == "flow-inspect"
    ]
    assert len(flow_rows) == 1
    assert flow_rows[0]["stages"] == stored_stages
    assert json.loads(flow_rows[0]["stages"]) == stages
    assert flow_rows[0]["project"] == "yoke"
    assert flow_rows[0]["status"] == "active"
    assert found.result_payload["rows"][0]["id"] == "run-inspect-001"
    assert found.result_payload["rows"][0]["flow"] == "flow-inspect"
    assert found.result_payload["rows"][0]["target_environment"] == "prod"
    assert found.result_payload["rows"][0]["target_tier"] == "persistent"
    assert found.result_payload["fields"] == [
        "id",
        "status",
        "current_stage",
        "created_at",
        "flow",
        "target_environment",
        "target_tier",
        "started_at",
        "completed_at",
    ]
    assert found.result_payload["rows"][0]["started_at"] is None
    assert found.result_payload["rows"][0]["completed_at"] is None
    assert [stage["state"] for stage in run_stages.result_payload["stages"]] == [
        "completed",
        "current",
        "pending",
    ]
