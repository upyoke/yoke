"""Client plan runner: independent chains, blocked followers and outcome precedence."""

from __future__ import annotations

from unittest import mock

from runtime.api.domain.qa_plan_execution_test_support import (
    TEST_EXECUTION_TARGET,
    TEST_ITEM_ID,
    TEST_ITEM_REF,
)
from yoke_contracts.api.function_call import ActorContext
from yoke_core.domain import machine_qa_plan_case_execution, qa_plan_execution
from yoke_core.domain.qa_plan_execution_result_state import QaPlanExecutionError


def _case(requirement_id, key, position, *, state, baseline="fresh-host", bp=1):
    return {
        "requirement_id": requirement_id,
        "item_id": TEST_ITEM_ID,
        "plan_id": 4,
        "case_key": key,
        "case_position": position,
        "baseline_position": bp,
        "host_baseline": baseline,
        "starting_state": state,
        "runner_id": "host_control",
    }


def _run(requirements, outcomes, *, with_payloads=False, refuse_checkin_at=None):
    """Run the client loop with each machine case answering from ``outcomes``."""
    calls: list[tuple[str, dict]] = []
    dispatched: list[int] = []

    def call_plan_function(**kwargs):
        calls.append((kwargs["function_id"], kwargs["payload"]))
        if kwargs["function_id"] == "qa.plan_execution.begin":
            return {
                "execution_id": "plan-execution-chains",
                "item_id": TEST_ITEM_ID,
                "transition_id": "implemented",
                "state": "active",
                "roster_digest": "digest",
                "cursor_ordinal": 0,
                "execution_target": TEST_EXECUTION_TARGET,
                "execution_target_digest": "target-digest",
                "requirements": requirements,
                "results": [],
            }
        if kwargs["function_id"] == "qa.plan_execution.heartbeat":
            checkins = [name for name, _ in calls].count(kwargs["function_id"])
            if checkins == refuse_checkin_at:
                raise QaPlanExecutionError("QA plan execution is not active")
        return {}

    def run_case(case, *, execution_id, ordinal, actor, **_):
        dispatched.append(int(case["requirement_id"]))
        answer = outcomes[int(case["requirement_id"])]
        if isinstance(answer, BaseException):
            raise answer
        outcome, verdict = answer
        return {
            "requirement_id": case["requirement_id"],
            "case_outcome": outcome,
            "verdict": verdict,
        }

    with (
        mock.patch.object(
            qa_plan_execution, "_call_plan_function", side_effect=call_plan_function
        ),
        mock.patch.object(
            machine_qa_plan_case_execution,
            "execute_plan_machine_case",
            side_effect=run_case,
        ),
    ):
        result = qa_plan_execution.execute_plan(
            public_ref=TEST_ITEM_REF,
            transition_id="implemented",
            actor=ActorContext(actor_id="7", session_id="chain-plan"),
        )
    if with_payloads:
        return result, dispatched, calls
    return result, dispatched, [name for name, _ in calls]


def test_every_machine_case_runs_through_its_own_plan_case_contract() -> None:
    requirements = [
        _case(101, "fresh-first", 1, state="baseline"),
        _case(102, "fresh-follow", 2, state="inherit"),
        _case(103, "fresh-again", 3, state="baseline"),
    ]
    passed = ("passed", "pass")
    result, dispatched, calls = _run(
        requirements, {101: passed, 102: passed, 103: passed}
    )

    assert result["state"] == "passed"
    assert dispatched == [101, 102, 103]
    assert "qa.plan_execution.advance" not in calls
    assert calls[-1] == "qa.plan_execution.complete"


def _aborts(calls_with_payloads):
    return [
        payload["reason"]
        for name, payload in calls_with_payloads
        if name == "qa.plan_execution.abort"
    ]


def test_a_failed_chain_blocks_only_its_followers_and_the_next_chain_runs() -> None:
    requirements = [
        _case(201, "anchor", 1, state="baseline"),
        _case(202, "follow-one", 2, state="inherit"),
        _case(203, "follow-two", 3, state="inherit"),
        _case(204, "next-chain", 4, state="baseline"),
        _case(205, "next-follow", 5, state="inherit"),
        _case(206, "as-found", 6, state="as_is", baseline=None),
    ]
    passed = ("passed", "pass")
    blocked = ("blocked_on_precondition", "blocked")
    result, dispatched, calls = _run(
        requirements,
        {
            201: ("failed", "fail"),
            202: blocked,
            203: blocked,
            204: passed,
            205: passed,
            206: passed,
        },
        with_payloads=True,
    )

    assert result["state"] == "failed"
    assert dispatched == [201, 202, 203, 204, 205, 206]
    assert [row["case_outcome"] for row in result["results"]] == [
        "failed",
        "blocked_on_precondition",
        "blocked_on_precondition",
        "passed",
        "passed",
        "passed",
    ]
    assert _aborts(calls) == ["qa-plan-case-failed: requirements 201"]
    names = [name for name, _ in calls]
    assert "qa.plan_review.begin" not in names
    assert "qa.plan_execution.complete" not in names
    assert "201" in result["recovery"] and "blocked" in result["recovery"]


def test_a_recorded_error_continues_like_a_failure() -> None:
    requirements = [
        _case(301, "alone", 1, state="as_is", baseline=None),
        _case(302, "next-chain", 2, state="baseline"),
        _case(303, "later-error", 3, state="baseline"),
    ]
    result, dispatched, calls = _run(
        requirements,
        {
            301: ("error", "error"),
            302: ("passed", "pass"),
            303: ("failed", "fail"),
        },
        with_payloads=True,
    )

    assert result["state"] == "error"
    assert dispatched == [301, 302, 303]
    assert _aborts(calls) == ["qa-plan-case-failed: requirements 301, 303"]


def test_a_raised_case_still_stops_the_whole_execution() -> None:
    requirements = [
        _case(401, "first", 1, state="baseline"),
        _case(402, "raises", 2, state="baseline"),
        _case(403, "never", 3, state="baseline"),
    ]
    result, dispatched, calls = _run(
        requirements,
        {401: ("failed", "fail"), 402: RuntimeError("host vanished")},
        with_payloads=True,
    )

    assert result["state"] == "error"
    assert dispatched == [401, 402]
    reasons = _aborts(calls)
    assert len(reasons) == 1
    assert not reasons[0].startswith("qa-plan-case-failed")
    assert "raised" in result["recovery"]


def test_a_refused_checkin_after_an_operator_abort_stops_the_execution() -> None:
    requirements = [
        _case(501, "first", 1, state="baseline"),
        _case(502, "second", 2, state="baseline"),
    ]
    result, dispatched, calls = _run(
        requirements,
        {501: ("failed", "fail"), 502: ("passed", "pass")},
        with_payloads=True,
        refuse_checkin_at=2,
    )

    assert result["state"] == "blocked_on_precondition"
    assert result["reason"] == "qa_checkin_refused"
    assert dispatched == [501]
    assert _aborts(calls) == []


def test_plan_state_aggregation_preserves_outcome_precedence() -> None:
    ordered = [
        ("passed", {"case_outcome": "passed", "verdict": "pass"}),
        (
            "needs_review",
            {"case_outcome": "needs_review", "verdict": "undetermined"},
        ),
        (
            "blocked_on_precondition",
            {
                "case_outcome": "blocked_on_precondition",
                "verdict": "undetermined",
            },
        ),
        ("failed", {"case_outcome": "failed", "verdict": "fail"}),
        ("waiting", {"case_outcome": "waiting", "verdict": "waiting"}),
        ("error", {"case_outcome": "error", "verdict": "error"}),
    ]

    for higher_index, (higher_state, higher_result) in enumerate(ordered):
        for lower_state, lower_result in ordered[:higher_index]:
            assert (
                qa_plan_execution._aggregate_state(lower_state, higher_result)
                == higher_state
            )
            assert (
                qa_plan_execution._aggregate_state(higher_state, lower_result)
                == higher_state
            )
