"""A live release's state reads off the steering report as a sentence.

Three shapes an operator has to tell apart without asking anyone: a run
holding red requirements, a run with nothing outstanding that is only
waiting to be driven, and a healthy run mid-flight. The rendered text is
asserted alongside the fields, because the operator reads the prose.
"""

from __future__ import annotations

import pytest

from runtime.api.steering_fleet_test_helpers import NOW, compose, seed_steering_scope
from yoke_core.domain.steering_fleet_report_projection import report_dict
from yoke_core.domain.steering_fleet_report_render import report_body


RUN_ID = "run-20260826-001"
STAGE = "item-qa"
STAGE_STARTED = "2026-08-26T08:00:00Z"


def _seed_run(conn, *, stage: str = STAGE, status: str = "executing") -> None:
    conn.execute(
        "INSERT INTO deployment_runs"
        "(id,project_id,flow,status,current_stage,created_at,started_at) "
        "VALUES (%s,1,'prod-release',%s,%s,%s,%s)",
        (RUN_ID, status, stage, STAGE_STARTED, STAGE_STARTED),
    )
    conn.execute(
        "INSERT INTO deployment_stage_receipts"
        "(run_id,stage_name,attempt_number,correlation_id,target_kind,"
        "target_name,status,executor,created_at) "
        "VALUES (%s,%s,1,%s,'environment','prod','running','operator',%s)",
        (RUN_ID, stage, f"{RUN_ID}:{stage}:1", STAGE_STARTED),
    )


def _seed_requirement(conn, *, requirement_id: int, member_item_id: int | None) -> None:
    conn.execute(
        "INSERT INTO qa_requirements"
        "(id,deployment_run_id,deployment_stage,deployment_member_item_id,"
        "qa_kind,qa_phase,blocking_mode,requirement_source,created_at) "
        "VALUES (%s,%s,%s,%s,'browser','post_deploy','blocking','flow_derived',%s)",
        (requirement_id, RUN_ID, STAGE, member_item_id, STAGE_STARTED),
    )


def _record_verdict(conn, *, requirement_id: int, verdict: str) -> None:
    conn.execute(
        "INSERT INTO qa_runs"
        "(qa_requirement_id,performed_by,qa_kind,verdict,created_at,completed_at) "
        "VALUES (%s,'agent','browser',%s,%s,%s)",
        (requirement_id, verdict, STAGE_STARTED, STAGE_STARTED),
    )


@pytest.fixture
def fleet(test_db):
    conn = seed_steering_scope(test_db)
    _seed_run(conn)
    return conn


def test_red_requirements_are_named_with_their_members(fleet) -> None:
    _seed_requirement(fleet, requirement_id=901, member_item_id=1)
    _seed_requirement(fleet, requirement_id=902, member_item_id=2)
    _seed_requirement(fleet, requirement_id=903, member_item_id=2)
    _record_verdict(fleet, requirement_id=901, verdict="fail")
    _record_verdict(fleet, requirement_id=902, verdict="error")
    _record_verdict(fleet, requirement_id=903, verdict="pass")
    fleet.commit()

    report = compose(fleet)

    run = report.deployment_runs[0]
    assert run.run_id == RUN_ID
    assert run.stage == STAGE
    assert run.outstanding == 2
    assert run.total_blocking == 3
    assert [red.requirement_id for red in run.red] == [901, 902]
    assert [red.member_ref for red in run.red] == ["YOK-1", "YOK-2"]
    assert run.needs_action is True
    assert report.runs_needing_action() == (run,)
    assert report.actionable is True


def test_the_report_sentence_carries_the_stage_age_and_the_counts(fleet) -> None:
    _seed_requirement(fleet, requirement_id=901, member_item_id=1)
    _record_verdict(fleet, requirement_id=901, verdict="fail")
    fleet.commit()

    body = report_body(compose(fleet))

    assert f"! {RUN_ID}  executing  flow prod-release  stage {STAGE} for 4h00m" in body
    assert "1 of 1 outstanding, 1 red" in body
    assert "red: YOK-1 #901 fail" in body
    assert f"Settle or waive each one, then re-drive {RUN_ID} to finalize." in body


def test_an_executing_run_with_nothing_outstanding_is_not_advised_to_re_drive(
    fleet,
) -> None:
    """A live driver already holds the run; a second drive can double-dispatch."""
    _seed_requirement(fleet, requirement_id=901, member_item_id=1)
    _record_verdict(fleet, requirement_id=901, verdict="pass")
    fleet.commit()

    report = compose(fleet)
    body = report_body(report)

    run = report.deployment_runs[0]
    assert run.status == "executing"
    assert run.outstanding == 0
    assert run.red == ()
    assert run.needs_action is False
    assert report.runs_needing_action() == ()
    assert f"  {RUN_ID}  executing  flow prod-release" in body
    assert "0 of 1 outstanding, 0 red" in body
    assert "re-drive" not in body
    assert "waiting only to be driven" not in body


def test_a_created_run_with_nothing_outstanding_is_advised_to_be_driven(
    fleet,
) -> None:
    fleet.execute(
        "UPDATE deployment_runs SET status='created' WHERE id=%s", (RUN_ID,)
    )
    fleet.commit()

    report = compose(fleet)
    body = report_body(report)

    run = report.deployment_runs[0]
    assert run.status == "created"
    assert run.outstanding == 0
    assert run.needs_action is True
    assert report.runs_needing_action() == (run,)
    assert f"! {RUN_ID}  created  flow prod-release" in body
    assert f"Nothing is outstanding; re-drive {RUN_ID} to finish it." in body
    assert "waiting only to be driven" in body


def test_a_healthy_run_is_reported_without_raising_an_alarm(fleet) -> None:
    _seed_requirement(fleet, requirement_id=901, member_item_id=1)
    _seed_requirement(fleet, requirement_id=902, member_item_id=2)
    _record_verdict(fleet, requirement_id=901, verdict="pass")
    fleet.commit()

    report = compose(fleet)
    body = report_body(report)

    run = report.deployment_runs[0]
    assert run.outstanding == 1
    assert run.red == ()
    assert run.needs_action is False
    assert report.runs_needing_action() == ()
    assert f"  {RUN_ID}  executing  flow prod-release" in body
    assert "1 of 2 outstanding, 0 red" in body
    # A run nobody has to decide about carries no recovery line: the
    # section is reporting where it is, not asking for anything.
    assert "re-drive" not in body


def test_a_terminal_run_leaves_the_section_entirely(fleet) -> None:
    fleet.execute(
        "UPDATE deployment_runs SET status='succeeded' WHERE id=%s", (RUN_ID,)
    )
    fleet.commit()

    report = compose(fleet)

    assert report.deployment_runs == ()
    assert "deployment runs —" not in report_body(report)


def test_the_machine_projection_carries_the_same_facts(fleet) -> None:
    _seed_requirement(fleet, requirement_id=901, member_item_id=1)
    _record_verdict(fleet, requirement_id=901, verdict="fail")
    fleet.commit()

    projected = report_dict(compose(fleet))

    row = projected["deployment_runs"][0]
    assert row["run_id"] == RUN_ID
    assert row["stage"] == STAGE
    assert row["stage_seconds"] == 4 * 3600
    assert row["outstanding"] == 1
    assert row["total_blocking"] == 1
    assert row["red"] == [
        {"requirement_id": 901, "verdict": "fail", "member_ref": "YOK-1"}
    ]
    assert row["needs_action"] is True
    assert projected["deployment_runs_needing_action"] == [row]


def test_the_fingerprint_moves_on_state_and_not_on_the_clock(fleet) -> None:
    _seed_requirement(fleet, requirement_id=901, member_item_id=1)
    fleet.commit()
    at_four_hours = compose(fleet, now=NOW).fingerprint()

    later = compose(fleet, now="2026-08-26T18:00:00Z")
    assert later.deployment_runs[0].stage_seconds == 10 * 3600
    assert later.fingerprint() == at_four_hours

    _record_verdict(fleet, requirement_id=901, verdict="fail")
    fleet.commit()
    assert compose(fleet, now=NOW).fingerprint() != at_four_hours


def _resolve_decision(conn, *, request_id: int, action: str, stage: str = STAGE) -> None:
    """A stage decision a person answered, as the decision surface records it."""
    conn.execute(
        "INSERT INTO decision_requests"
        "(id,kind,subject_type,subject_key,project_id,status,"
        "resolution_action,resolved_at,approval_mode,created_at) "
        "VALUES (%s,'deployment_stage_approval','deployment_stage',%s,1,"
        "'resolved',%s,%s,'any',%s)",
        (request_id, f"{RUN_ID}:{stage}", action, STAGE_STARTED, STAGE_STARTED),
    )
    conn.commit()


def test_an_answered_decision_the_run_never_acted_on_is_named(fleet) -> None:
    _seed_requirement(fleet, requirement_id=901, member_item_id=1)
    _seed_requirement(fleet, requirement_id=902, member_item_id=2)
    _record_verdict(fleet, requirement_id=901, verdict="pass")
    _record_verdict(fleet, requirement_id=902, verdict="pass")
    _resolve_decision(fleet, request_id=8385, action="approve")

    report = compose(fleet)
    body = report_body(report)

    answered = report.deployment_runs[0].answered_decision
    assert answered is not None
    assert answered.request_id == 8385
    assert answered.action == "approve"
    assert report.runs_needing_action() == (report.deployment_runs[0],)
    assert "decision #8385 approved 4h00m ago" in body
    assert "the run is still waiting at this stage" in body
    assert f"re-drive {RUN_ID} so the runner acts on it" in body


def test_an_answered_reject_still_sitting_in_flight_is_named(fleet) -> None:
    _seed_requirement(fleet, requirement_id=901, member_item_id=1)
    _record_verdict(fleet, requirement_id=901, verdict="pass")
    _resolve_decision(fleet, request_id=8386, action="reject")

    body = report_body(compose(fleet))

    assert "decision #8386 rejected 4h00m ago" in body
    assert "a reject fails the stage" in body


def test_a_decision_for_a_stage_the_run_left_is_not_a_stall(fleet) -> None:
    """History, not a stall: the run is standing somewhere else now."""
    _seed_requirement(fleet, requirement_id=901, member_item_id=1)
    _resolve_decision(fleet, request_id=8387, action="approve", stage="earlier-gate")

    report = compose(fleet)

    assert report.deployment_runs[0].answered_decision is None


def test_an_answered_decision_changes_the_report_identity(fleet) -> None:
    _seed_requirement(fleet, requirement_id=901, member_item_id=1)
    _record_verdict(fleet, requirement_id=901, verdict="pass")
    fleet.commit()
    before = compose(fleet).fingerprint()

    _resolve_decision(fleet, request_id=8385, action="approve")

    assert compose(fleet).fingerprint() != before
