"""A stopped setup-only mission is an execution error, never a review."""

import pytest

from runtime.api.fixtures.qa_captured_plan_review_fixture import captured_plan_review
from yoke_core.domain.qa_plan_execution_lifecycle import finish_plan_execution
from yoke_core.domain.qa_plan_review import begin_plan_review


@pytest.mark.parametrize(
    "artifact_type",
    [None, "diagnostic", "starting_state_restore", "fixture_project_disposal"],
)
@pytest.mark.parametrize("state", ["aborted", "error"])
@pytest.mark.parametrize("bundle_exists", [False, True])
def test_stopped_mission_settles_setup_docket(
    test_db, artifact_type, state, bundle_exists
):
    execution, requirement_id, run_id = captured_plan_review(test_db, 9783)
    execution["roster"][0].update(
        runner_id="agent_mission",
        method_id="exploratory-mission",
        method_config={"executor": "informed_subagent"},
    )
    test_db.execute(
        "UPDATE qa_runs SET performed_by='agent_mission',execution_status='captured' "
        "WHERE id=%s",
        (run_id,),
    )
    if artifact_type is None:
        test_db.execute("DELETE FROM qa_artifacts WHERE qa_run_id=%s", (run_id,))
    else:
        test_db.execute(
            "UPDATE qa_artifacts SET artifact_type=%s WHERE qa_run_id=%s",
            (artifact_type, run_id),
        )
    if bundle_exists:
        assert begin_plan_review(test_db, execution) is not None
    reason = "blocked_on_precondition: sandbox denied; use a compatible declared host"
    finish_plan_execution(test_db, execution, state=state, reason=reason)
    row = test_db.execute(
        "SELECT execution_status,case_outcome,verdict,verdict_reason "
        "FROM qa_runs WHERE id=%s",
        (run_id,),
    ).fetchone()
    assert tuple(row)[:3] == ("capture_failed", "blocked_on_precondition", "error")
    assert reason in row[3]
    assert "run a fresh mission" in row[3]
    assert begin_plan_review(test_db, execution, completed_captures_only=True) is None
    assert (
        test_db.execute(
            "SELECT count(*) FROM decision_requests WHERE kind='qa_needs_review' "
            "AND subject_key=%s AND status='pending'",
            (str(requirement_id),),
        ).fetchone()[0]
        == 0
    )


def test_stopped_mission_keeps_real_proof_reviewable(test_db):
    execution, _, run_id = captured_plan_review(test_db, 9784)
    execution["roster"][0].update(
        runner_id="agent_mission",
        method_id="exploratory-mission",
        method_config={"executor": "informed_subagent"},
    )
    test_db.execute(
        "UPDATE qa_runs SET performed_by='agent_mission',execution_status='captured' "
        "WHERE id=%s",
        (run_id,),
    )
    finish_plan_execution(
        test_db, execution, state="aborted", reason="later setup failed"
    )
    assert (
        test_db.execute(
            "SELECT verdict FROM qa_runs WHERE id=%s",
            (run_id,),
        ).fetchone()[0]
        is None
    )
    bundle = begin_plan_review(test_db, execution, completed_captures_only=True)
    assert [case["capture_run_id"] for case in bundle["cases"]] == [run_id]


def test_setup_stop_guidance_names_diagnostic_evidence():
    from yoke_core.domain.qa_mission_stop_settlement import stopped_mission_guidance

    guidance = stopped_mission_guidance("--item example", "execution")
    assert "attach blocker evidence as `diagnostic`" in guidance
    assert "without human review" in guidance
