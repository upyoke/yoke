"""Client plan runner: machine chains, blocked followers and outcome precedence."""

from __future__ import annotations

from unittest import mock

from runtime.api.domain.qa_plan_execution_test_support import (
    TEST_EXECUTION_TARGET,
    TEST_ITEM_ID,
    TEST_ITEM_REF,
)
from yoke_contracts.api.function_call import ActorContext
from yoke_core.domain import machine_qa_plan_case_execution, qa_plan_execution


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


def _run(requirements, outcomes):
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
        return {}

    def run_case(case, *, execution_id, ordinal, actor, **_):
        dispatched.append(int(case["requirement_id"]))
        outcome, verdict = outcomes[int(case["requirement_id"])]
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


def test_a_failed_case_records_its_inheriting_followers_then_stops() -> None:
    requirements = [
        _case(201, "anchor", 1, state="baseline"),
        _case(202, "follow-one", 2, state="inherit"),
        _case(203, "follow-two", 3, state="inherit"),
        _case(204, "next-chain", 4, state="baseline"),
    ]
    blocked = ("blocked_on_precondition", "blocked")
    result, dispatched, calls = _run(
        requirements,
        {201: ("failed", "fail"), 202: blocked, 203: blocked},
    )

    assert result["state"] == "failed"
    assert dispatched == [201, 202, 203]
    assert [row["requirement_id"] for row in result["results"]] == [201, 202, 203]
    assert [row["case_outcome"] for row in result["results"][1:]] == [
        "blocked_on_precondition",
        "blocked_on_precondition",
    ]
    assert "qa.plan_execution.abort" in calls


def test_an_unchained_failure_stops_without_touching_the_next_chain() -> None:
    requirements = [
        _case(301, "alone", 1, state="as_is", baseline=None),
        _case(302, "next-chain", 2, state="baseline"),
    ]
    result, dispatched, _ = _run(requirements, {301: ("failed", "fail")})

    assert result["state"] == "failed"
    assert dispatched == [301]


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
