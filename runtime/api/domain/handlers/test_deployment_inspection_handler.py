"""Handler coverage for deployment inventory and progress reads."""

from __future__ import annotations

import json

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
    )
    stages = [
        {"name": "build", "runner": "local_command"},
        {"name": "deploy", "runner": "local_command"},
        {"name": "verify", "runner": "local_command"},
    ]
    test_db.execute(
        "UPDATE deployment_flows SET stages=%s WHERE id=%s",
        (json.dumps(stages), "flow-inspect"),
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
    assert any(row["id"] == "flow-inspect" for row in flows.result_payload["rows"])
    assert found.result_payload["rows"][0]["id"] == "run-inspect-001"
    assert [stage["state"] for stage in run_stages.result_payload["stages"]] == [
        "completed",
        "current",
        "pending",
    ]
