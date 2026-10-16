"""Full preparation receipts survive storage, registered reads and recovery."""

import json
from types import SimpleNamespace
from unittest.mock import patch

from runtime.api.domain.handlers.deployment_handler_test_support import (
    deployment_request,
)
from runtime.api.fixtures.native_instant_database import blank_database
from yoke_cli.transport.relay_telemetry import TRANSPORT_FAILED_CODE
from yoke_contracts.api.function_call import (
    FunctionCallResponse,
    FunctionError,
    TargetRef,
)
from yoke_contracts.timestamps import parse_instant
from yoke_core.domain import deploy_pipeline_bound_inputs as driver
from yoke_core.domain import deployment_runs_crud_query as reads
from yoke_core.domain.deployment_run_bound_sources import (
    BOUND_SOURCES_PREPARE_FUNCTION_ID,
)
from yoke_core.domain.handlers.deployment_runs import handle_deployment_run_get


def test_shell_pipeline_receipt_round_trip_recovers_exact_committed_request(
    monkeypatch,
):
    run_id = "run-receipt"
    stamp = "2026-10-15T15:03:04.335256Z"
    snapshot = {
        "requirements": [
            {
                "instructions": "curl -fsSL https://upyoke.com/install | sh\n"
                'printf "%s" "ready | complete"',
                "expected_outcome": "All checks pass | full evidence retained",
            }
        ],
    }
    bound = {
        "inputs": {"consumer_sha": "b" * 40},
        "preparation_receipt": {
            "request_id": "prepare-request",
            "stage_name": "hosted-release",
            "members": [{"public_ref": "ITEM-1", "requirement_snapshot": snapshot}],
            "rebound": [],
        },
    }
    bound_text = json.dumps(bound)
    carried = {"schema": 1, "items": [], "commits": []}
    expected = {
        "id": run_id,
        "project": "project",
        "flow": "flow",
        "target_tier": "persistent",
        "target_environment": "prod",
        "release_lineage": "a" * 40,
        "status": "executing",
        "current_stage": "hosted-release",
        "created_at": stamp,
        "started_at": stamp,
        "completed_at": None,
        "created_by": "operator",
        "carried_work": carried,
        "bound_sources": bound_text,
        "artifact_identity": "artifact|digest",
        "composition_resolution": json.dumps({"reason": "ready | frozen"}),
        "composition_frozen_at": stamp,
        "requirement_snapshot": json.dumps(snapshot),
    }
    with blank_database() as conn:
        conn.execute("CREATE TABLE projects (id integer PRIMARY KEY, slug text)")
        conn.execute("INSERT INTO projects VALUES (1, 'project')")
        conn.execute("CREATE TABLE environments (id integer PRIMARY KEY, name text)")
        conn.execute("INSERT INTO environments VALUES (2, 'prod')")
        conn.execute(
            "CREATE TABLE deployment_runs (id text PRIMARY KEY, project_id integer, "
            "flow text, target_tier text, target_environment_id integer, "
            "release_lineage text, status text, current_stage text, "
            "created_at timestamptz, started_at timestamptz, completed_at timestamptz, "
            "created_by text, carried_work text, bound_sources text, "
            "artifact_identity text, composition_resolution text, "
            "composition_frozen_at timestamptz, requirement_snapshot text)"
        )
        values = dict(expected)
        values["project"] = 1
        values["target_environment"] = 2
        values["carried_work"] = json.dumps(carried)
        for name in ("created_at", "started_at", "composition_frozen_at"):
            values[name] = parse_instant(stamp)
        conn.execute(
            "INSERT INTO deployment_runs VALUES (" + ",".join(["%s"] * 18) + ")",
            tuple(values.values()),
        )
        proxy = SimpleNamespace(execute=conn.execute, close=lambda: None)
        monkeypatch.setattr(reads, "connect", lambda *_: proxy)
        outcome = handle_deployment_run_get(
            deployment_request(
                function="deployment_runs.get",
                target=TargetRef(kind="workflow_run", workflow_run_id=run_id),
            )
        )
        assert outcome.primary_success
        response = FunctionCallResponse(
            function="deployment_runs.get",
            version="v1",
            success=True,
            result=outcome.result_payload,
        )
        readback = FunctionCallResponse.model_validate_json(response.model_dump_json())
        assert readback.result["run"] == expected
        assert json.loads(readback.result["run"]["bound_sources"]) == bound
        assert readback.result["attestation_warnings"] == []

        lost = FunctionCallResponse(
            function=BOUND_SOURCES_PREPARE_FUNCTION_ID,
            version="v1",
            success=False,
            request_id="prepare-request",
            error=FunctionError(code=TRANSPORT_FAILED_CODE, message="response lost"),
        )
        members = ["OLD-1"]
        with patch.object(
            driver, "call_dispatcher", side_effect=[lost, readback]
        ) as calls:
            inputs, reason = driver.bound_inputs_for_dispatch(
                {
                    "input_bindings": {
                        "consumer_sha": {"project": "consumer", "branch": "main"}
                    }
                },
                name="hosted-release",
                run_id=run_id,
                bound_inputs={},
                member_items=members,
            )
        assert inputs == {"consumer_sha": "b" * 40}
        assert reason == ""
        assert members == ["ITEM-1"]
        assert [call.kwargs["function_id"] for call in calls.call_args_list] == [
            BOUND_SOURCES_PREPARE_FUNCTION_ID,
            "deployment_runs.get",
        ]
        assert (
            conn.execute(
                "SELECT bound_sources FROM deployment_runs WHERE id=%s", (run_id,)
            ).fetchone()[0]
            == bound_text
        )
