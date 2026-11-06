# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from contextlib import nullcontext

import pytest

from runtime.api.domain.handlers.deployment_handler_test_support import (
    deployment_request,
)

from runtime.api.fixtures.deployment_scoped_qa_run_fixture import (
    ITEM_QA_STAGE,
    item_qa_stage_definitions,
    seed_run_standing_on_qa_stage,
)

from runtime.api.steering_fleet_test_helpers import seed_steering_scope

from yoke_core.domain import db_helpers, deploy_pipeline as pipeline

from yoke_core.domain.deployment_qa_stage_outstanding import QaStageOutstanding

from yoke_core.domain.deployment_run_completion_preconditions import (
    unresolved_blocking_qa,
)

from yoke_core.domain.handlers import deployment_run_execution_qa as handler


@pytest.fixture
def scoped_run(test_db, monkeypatch):
    conn = seed_steering_scope(test_db)
    run_id = "run-scoped-report"
    member = 42
    stages = item_qa_stage_definitions(None)
    seed_run_standing_on_qa_stage(
        conn,
        run_id=run_id,
        project="yoke",
        stages=stages,
        members=(member,),
        lineage="c" * 40,
    )
    assert unresolved_blocking_qa(conn, run_id) == []
    monkeypatch.setattr(handler, "_driven_run", lambda request, function: run_id)
    monkeypatch.setattr(db_helpers, "connect", lambda: nullcontext(conn))

    def call(function, run, payload):
        assert function == "deployment_runs.execution.qa_pending"
        assert run == run_id
        outcome = handler.handle_deployment_execution_qa_pending(
            deployment_request(function=function, payload=payload)
        )
        assert outcome.primary_success
        return outcome.result_payload

    monkeypatch.setattr(pipeline.control_plane, "_call", call)
    return run_id, member, stages


@pytest.fixture
def awaiting_driver(scoped_run, monkeypatch):
    run_id, member, stages = scoped_run
    context = {
        "run": {
            "id": run_id,
            "project": "yoke",
            "flow": "qa-flow",
            "status": "executing",
        },
        "members": [{"public_ref": f"YOK-{member}"}],
        "stages": stages[1:],
    }
    monkeypatch.setattr(pipeline.control_plane, "execution_context", lambda r: context)
    monkeypatch.setattr(pipeline.control_plane, "project_field", lambda *a: "")
    monkeypatch.setattr(pipeline, "resolve_project_checkout_path", lambda p: "/repo")
    monkeypatch.setattr(pipeline, "resolve_flow_gate_branch", lambda *a: "main")
    monkeypatch.setattr(
        pipeline, "_resolve_and_verify_branch", lambda *a, **k: (True, "42", "main")
    )
    monkeypatch.setattr(pipeline, "_set_deploy_stage", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "_emit_run_event", lambda *a, **k: None)
    monkeypatch.setattr(
        pipeline,
        "dispatch_until_qa_resolves",
        lambda *a, **k: (
            -4,
            f"member {member}: no completed scoped QA execution exists",
        ),
    )

    return run_id, member
