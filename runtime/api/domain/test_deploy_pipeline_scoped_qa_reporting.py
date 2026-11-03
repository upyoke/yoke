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


def test_driver_wait_counts_member_without_selected_cases(awaiting_driver, capsys):
    run_id, member = awaiting_driver
    assert pipeline.run_pipeline(run_id, sd="/tmp/sd") == pipeline.EXIT_AWAITING_QA
    report = capsys.readouterr().err
    assert "1 blocking QA obligation(s)" in report
    assert f"member {member}:" in report
    assert "Blocking QA remains:" in report
    assert "remove-item" in report
    assert "Nothing is outstanding" not in report


@pytest.mark.parametrize(
    "error_code", ["read_deadline_exceeded", "scoped_qa_report_unavailable"]
)
def test_failed_report_preserves_awaiting_qa_outcome(
    awaiting_driver, monkeypatch, capsys, error_code
):
    run_id, member = awaiting_driver
    diagnostic = (
        f"member {member}: no completed scoped QA execution exists; "
        "timed out after 1800s awaiting scoped QA."
    )
    monkeypatch.setattr(
        pipeline, "dispatch_until_qa_resolves", lambda *a, **k: (-4, diagnostic)
    )
    report_reads = []
    events = []

    def unavailable(run, stage):
        report_reads.append((run, stage))
        raise pipeline.control_plane.DeploymentControlPlaneError(
            f"{error_code}: fresh report read failed", code=error_code
        )

    monkeypatch.setattr(pipeline.control_plane, "held_qa_report_lines", unavailable)
    monkeypatch.setattr(
        pipeline, "_emit_run_event", lambda event, *a, **k: events.append(event)
    )

    assert pipeline.run_pipeline(run_id, sd="/tmp/sd") == pipeline.EXIT_AWAITING_QA
    captured = capsys.readouterr()
    assert diagnostic in captured.err
    assert error_code in captured.err
    assert "fresh QA report unavailable" in captured.err
    assert "last QA blocker diagnostic" in captured.err
    assert "blocking QA obligation(s)" not in captured.err
    assert "Nothing is outstanding" not in captured.err
    assert "completed successfully" not in captured.out
    assert report_reads == [(run_id, ITEM_QA_STAGE)]
    assert events == ["DeploymentRunStageStarted"]


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


@pytest.mark.parametrize("other_stage", [None, "earlier-qa", ""])
def test_scoped_report_counts_member_once_and_keeps_other_stages(test_db, other_stage):
    from runtime.api.fixtures.deployment_scoped_qa_run_fixture import seed_member_qa_case
    from runtime.api.domain.test_steering_fleet_report_deployment_run_facts import (
        _seed_requirement,
    )

    conn = seed_steering_scope(test_db)
    run_id = "run-scoped-member-report"
    requirement_id = seed_member_qa_case(conn, run_id=run_id, member_item_id=42)
    if other_stage is not None:
        _seed_requirement(conn, run_id=run_id, requirement_id=9001, member_item_id=None)
        conn.execute(
            "UPDATE qa_requirements SET deployment_stage=%s WHERE id=%s",
            (other_stage, 9001),
        )
    conn.commit()

    result = handler._qa_pending(conn, run_id, ITEM_QA_STAGE)
    details = [line for line in result["held_report"] if line.startswith("  - ")]
    count = 1 if other_stage is None else 2
    assert f"{count} blocking QA obligation(s)" in result["held_report"][0]
    assert len(details) == count
    assert len(result["unresolved"]) == count
    assert any(f"requirement #{requirement_id}" in line for line in result["unresolved"])
    assert not any(f"requirement #{requirement_id} (" in line for line in details)
    if other_stage is not None:
        assert any("requirement #9001" in line for line in details)


def test_report_without_scoped_summary_keeps_run_requirements(test_db, monkeypatch):
    from runtime.api.fixtures.deployment_scoped_qa_run_fixture import seed_member_qa_case
    from yoke_core.domain import deployment_qa_stage_outstanding as reader

    conn = seed_steering_scope(test_db)
    run_id = "run-unscoped-member-report"
    seed_member_qa_case(conn, run_id=run_id, member_item_id=42)
    monkeypatch.setattr(reader, "qa_stage_outstanding", lambda *a, **k: None)

    result = handler._qa_pending(conn, run_id, ITEM_QA_STAGE)
    assert "1 blocking QA obligation(s)" in result["held_report"][0]
    assert result["held_report"][1] == f"  - {result['unresolved'][0]}"
