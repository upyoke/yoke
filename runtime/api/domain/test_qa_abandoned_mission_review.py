"""A stopped walk settles empty review dockets without judging the case."""

import pytest

from runtime.api.domain.machine_qa_session_seed import seed_qa_session
from runtime.api.fixtures.qa_captured_plan_review_fixture import captured_plan_review
from yoke_core.domain.qa_host_idle_hold import IDLE_HOLD_RELEASED_REASON
from yoke_core.domain.qa_pending_agent_review import pending_review_requirements
from yoke_core.domain.qa_plan_execution_lifecycle import (
    STALE_PLAN_EXECUTION_REASON,
    finish_plan_execution,
    reap_stale_plan_executions,
)
from yoke_core.domain.qa_plan_execution_store import canonical, roster_digest
from yoke_core.domain.qa_plan_review import begin_plan_review


@pytest.mark.parametrize(
    "artifact_type",
    [None, "diagnostic", "starting_state_restore", "terminal_screenshot"],
)
@pytest.mark.parametrize(
    "reason",
    [STALE_PLAN_EXECUTION_REASON, IDLE_HOLD_RELEASED_REASON, "operator stopped the walk"],
)
def test_aborted_mission_settles_only_review_without_product_evidence(
    test_db, artifact_type, reason,
):
    execution, requirement_id, run_id = captured_plan_review(test_db, 9786)
    seed_qa_session(test_db, execution["session_id"], messageable=True)
    roster = execution["roster"]
    roster[0].update(
        runner_id="agent_mission",
        method_id="exploratory-mission",
        method_config={"executor": "informed_subagent", "os": "macos"},
    )
    execution["roster_digest"] = roster_digest(roster)
    test_db.execute(
        "UPDATE qa_plan_executions SET roster_json=%s,roster_digest=%s WHERE id=%s",
        (canonical(roster), execution["roster_digest"], execution["id"]),
    )
    test_db.execute(
        "UPDATE qa_runs SET performed_by='agent_mission',execution_status='captured',"
        "capture_degraded_reason='agent_mission_docket:walker_artifacts_not_yet_attached' "
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
    assert begin_plan_review(test_db, execution)["state"] == "pending"
    if reason == STALE_PLAN_EXECUTION_REASON:
        test_db.execute(
            "UPDATE harness_sessions SET ended_at=CURRENT_TIMESTAMP WHERE session_id=%s",
            (execution["session_id"],),
        )
        test_db.commit()
        (settled,) = reap_stale_plan_executions(test_db)
        assert settled["execution_id"] == str(execution["id"])
        assert settled["state"] == "aborted"
    elif reason == IDLE_HOLD_RELEASED_REASON:
        # The idle watchdog hands off the lease before finalizing the execution.
        finish_plan_execution(
            test_db, execution, state="aborted", reason=f"{reason}: returned host"
        )
    else:
        owner = test_db.execute(
            "SELECT ended_at,terminated_at FROM harness_sessions WHERE session_id=%s",
            (execution["session_id"],),
        ).fetchone()
        assert tuple(owner) == (None, None)
        finish_plan_execution(test_db, execution, state="aborted", reason=reason)
        assert execution["state"] == "aborted"
    run = test_db.execute(
        "SELECT case_outcome,verdict,verdict_reason FROM qa_runs WHERE id=%s",
        (run_id,),
    ).fetchone()
    review = test_db.execute(
        "SELECT state,reviewer_actor_id,reviewer_session_id,reviewed_at "
        "FROM qa_plan_review_bundles WHERE execution_id=%s",
        (execution["id"],),
    ).fetchone()
    assert run["verdict"] is None
    pending = pending_review_requirements(test_db, [requirement_id], stopped_only=True)
    if artifact_type == "terminal_screenshot":
        assert run["case_outcome"] == "needs_review"
        assert review["state"] == "pending"
        assert requirement_id in pending
    else:
        assert run["case_outcome"] == "blocked_on_precondition"
        assert reason in run["verdict_reason"]
        assert tuple(review) == ("completed", None, None, None)
        assert pending == {}
    artifacts = test_db.execute(
        "SELECT artifact_type FROM qa_artifacts WHERE qa_run_id=%s", (run_id,),
    ).fetchall()
    assert [row[0] for row in artifacts] == ([] if artifact_type is None else [artifact_type])
