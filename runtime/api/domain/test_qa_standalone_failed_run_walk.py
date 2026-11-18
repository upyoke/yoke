"""A standalone run walks its prepared missions before failed cases settle it."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from yoke_core.domain import machine_qa_plan_case_execution as machine
from yoke_core.domain.qa_case_execution import QaCaseExecutionError
from yoke_core.domain.qa_case_mission_execution import execute_mission_case
from yoke_core.domain.qa_plan_execution_result_state import QaPlanExecutionError
from yoke_core.domain.qa_plan_execution_run import execute_begun_plan
from yoke_core.domain.qa_plan_reviewed_state import (
    REVIEW_COMPLETE_REASON,
    reviewed_execution_state,
    reviewed_release_reason,
)


def _host(requirement_id, position, *, state="baseline"):
    return {
        "requirement_id": requirement_id,
        "runner_id": "host_control",
        "case_key": f"host-{requirement_id}",
        "case_position": position,
        "baseline_position": 1,
        "host_baseline": "fresh-host",
        "starting_state": state,
    }


def _mission(requirement_id, position, *, state="baseline"):
    return {
        **_host(requirement_id, position, state=state),
        "runner_id": "agent_mission",
        "case_key": f"mission-{requirement_id}",
        "verdict_path": "agent",
    }


FAILED = {"case_outcome": "failed", "verdict": "fail"}
BLOCKED = {"case_outcome": "blocked_on_precondition", "verdict": "blocked"}
PREPARED = {"case_outcome": "needs_review", "verdict": "undetermined"}


def _run(
    monkeypatch, requirements, outcomes, *, standalone=True, bundle=True, refusal=None
):
    def run_case(case, **_):
        rid = int(case["requirement_id"])
        return {"requirement_id": rid, "run_id": rid * 10, **outcomes[rid]}

    monkeypatch.setattr(machine, "execute_plan_machine_case", run_case)
    monkeypatch.setattr(machine, "execute_plan_agent_mission_case", run_case)
    calls = []

    def call(**kwargs):
        calls.append((kwargs["function_id"], kwargs["payload"]))
        if kwargs["function_id"] == "qa.plan_review.begin" and refusal:
            raise QaPlanExecutionError(refusal)
        if kwargs["function_id"] == "qa.plan_review.begin" and bundle:
            return {"state": "walking", "review_bundle": {"bundle_id": "b"}}
        return {}

    execution = {"execution_id": "standalone-execution"}
    if standalone:
        execution["standalone_plan_id"] = 9
    else:
        execution["item_id"] = 4
    begun = SimpleNamespace(
        requirements=requirements,
        cursor=0,
        resolved_base_url=None,
        recorded_results=[],
        recorded_ordinals=[],
        selected_machine=None,
        host_free_cases_ahead=False,
    )
    result = execute_begun_plan(
        execution=execution,
        begun=begun,
        target=None,
        resolved_actor=None,
        transition_id=None,
        expected_branch=None,
        expected_sha=None,
        timeout_seconds=60,
        checkout_path=None,
        allow_tree_mismatch=False,
        call_plan_function=call,
    )
    names = [name for name, _ in calls]
    aborts = [p["reason"] for name, p in calls if name == "qa.plan_execution.abort"]
    return result, names, aborts


def test_failed_case_still_walks_an_independent_prepared_mission(monkeypatch):
    requirements = [_host(601, 1), _host(602, 2, state="inherit"), _mission(603, 3)]
    result, names, aborts = _run(
        monkeypatch, requirements, {601: FAILED, 602: BLOCKED, 603: PREPARED}
    )

    assert aborts == []
    assert "qa.plan_review.begin" in names
    assert "qa.plan_execution.complete" not in names
    assert result["state"] == "walking"
    assert result["review_bundle"] == {"bundle_id": "b"}
    assert [row["case_outcome"] for row in result["results"]] == [
        "failed",
        "blocked_on_precondition",
        "needs_review",
    ]
    assert "601" in result["recovery"] and "settles" in result["recovery"]


def test_item_runs_keep_closing_on_the_failure(monkeypatch):
    requirements = [_host(611, 1), _mission(612, 2)]
    result, names, aborts = _run(
        monkeypatch, requirements, {611: FAILED, 612: PREPARED}, standalone=False
    )

    assert aborts == ["qa-plan-case-failed: requirements 611"]
    assert "qa.plan_review.begin" not in names
    assert result["state"] == "failed"


def test_mission_blocked_behind_the_failure_closes_the_run(monkeypatch):
    requirements = [_host(621, 1), _mission(622, 2, state="inherit")]
    result, names, aborts = _run(monkeypatch, requirements, {621: FAILED, 622: BLOCKED})

    assert aborts == ["qa-plan-case-failed: requirements 621"]
    assert "qa.plan_review.begin" not in names
    assert result["state"] == "failed"


def test_failed_run_closes_when_review_has_nothing_to_walk(monkeypatch):
    requirements = [_host(631, 1), _mission(632, 2)]
    result, names, aborts = _run(
        monkeypatch, requirements, {631: FAILED, 632: PREPARED}, bundle=False
    )

    assert aborts == ["qa-plan-case-failed: requirements 631"]
    assert "qa.plan_execution.complete" not in names
    assert result["state"] == "failed"


def test_refused_review_begin_falls_back_to_the_failed_case_abort(monkeypatch):
    refusal = (
        "plan_review_begin_failed: agent-verdict case 642 execution result "
        "does not identify its capture run"
    )
    requirements = [_host(641, 1), _mission(642, 2)]
    result, names, aborts = _run(
        monkeypatch, requirements, {641: FAILED, 642: PREPARED}, refusal=refusal
    )

    assert "qa.plan_review.begin" in names
    assert aborts == ["qa-plan-case-failed: requirements 641"]
    assert "qa.plan_execution.complete" not in names
    assert result["state"] == "failed"
    assert result["review_bundle"] is None
    assert "641" in result["recovery"] and refusal in result["recovery"]


def test_review_settles_failed_and_names_every_failed_requirement():
    recorded = [
        {"requirement_id": 41, "result": FAILED},
        {"requirement_id": 42, "result": BLOCKED},
        {"requirement_id": 43, "result": PREPARED},
    ]
    verdicts = {43: ("pass", "Mission checked.")}

    assert reviewed_execution_state(recorded, verdicts) == "failed"
    assert (
        reviewed_release_reason(recorded, verdicts)
        == "qa-plan-case-failed: requirements 41"
    )
    clean = [{"requirement_id": 43, "result": PREPARED}]
    assert reviewed_release_reason(clean, verdicts) == REVIEW_COMPLETE_REASON
    assert (
        reviewed_release_reason(clean, {43: ("fail", "Broken.")})
        == "qa-plan-case-failed: requirements 43"
    )


def _standalone_case(state):
    case = {
        "requirement_id": 51,
        "runner_id": "agent_mission",
        "starting_state": "baseline",
        "plan_id": 9,
        "project": "example",
        "standalone_execution_id": "ended-execution",
    }
    if state != "absent":
        case["standalone_execution_state"] = state
    return case


@pytest.mark.parametrize("state", ["aborted", "completed", "error"])
def test_refusal_never_points_a_terminal_execution_at_resume(state):
    with pytest.raises(QaCaseExecutionError) as caught:
        execute_mission_case(_standalone_case(state))

    message = str(caught.value)
    assert message.startswith("qa_single_mission_standalone")
    assert "--resume-execution-id" not in message
    assert "`yoke qa plan run --plan 9 --project example`" in message


def test_refusal_resumes_a_live_execution():
    with pytest.raises(QaCaseExecutionError) as caught:
        execute_mission_case(_standalone_case("walking"))

    assert "--resume-execution-id ended-execution`" in str(caught.value)
    assert "fresh" not in str(caught.value)


def test_refusal_from_an_older_server_names_both_recipes():
    with pytest.raises(QaCaseExecutionError) as caught:
        execute_mission_case(_standalone_case("absent"))

    message = str(caught.value)
    assert "--resume-execution-id ended-execution" in message
    assert "qa_resume_terminal" in message
