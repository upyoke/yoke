"""Held-stage driver reports include QA members with no requirement rows."""

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
    monkeypatch.setattr(handler, "_locked_run", lambda request, function: run_id)
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


def test_driver_wait_counts_member_without_selected_cases(
    scoped_run, monkeypatch, capsys
):
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
    monkeypatch.setattr(pipeline.control_plane, "seed_qa", lambda r: None)
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

    assert pipeline.run_pipeline(run_id, sd="/tmp/sd") == pipeline.EXIT_AWAITING_QA
    report = capsys.readouterr().err
    assert "1 blocking QA obligation(s)" in report
    assert f"member {member}:" in report
    assert "Blocking QA remains:" in report
    assert "remove-item" in report
    assert "Nothing is outstanding" not in report


def test_several_blockers_count_one_member(scoped_run, monkeypatch):
    run_id, member, _ = scoped_run
    from yoke_core.domain import deployment_qa_stage_outstanding as reader

    monkeypatch.setattr(
        reader,
        "qa_stage_outstanding",
        lambda *a, **k: QaStageOutstanding(
            lines=(
                f"member {member}: no completed scoped QA execution exists",
                f"member {member}: no concrete QA cases are materialized",
            ),
            subjects=1,
            waiting=1,
            waiting_members=(member,),
        ),
    )
    report = "\n".join(
        pipeline.control_plane.held_qa_report_lines(run_id, ITEM_QA_STAGE)
    )
    assert "1 blocking QA obligation(s)" in report
    assert "no completed scoped QA execution exists" in report
    assert "no concrete QA cases are materialized" in report


def test_missing_server_report_refuses_without_claiming_zero(monkeypatch):
    monkeypatch.setattr(pipeline.control_plane, "_call", lambda *a: {"unresolved": []})
    with pytest.raises(
        pipeline.control_plane.DeploymentControlPlaneError,
        match="scoped_qa_report_unavailable",
    ):
        pipeline.control_plane.held_qa_report_lines(
            "run-older-serving-build", ITEM_QA_STAGE
        )
