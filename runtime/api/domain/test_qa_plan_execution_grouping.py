"""Baseline-group aggregation and durable plan-resume coverage."""

from __future__ import annotations

from unittest import mock

from runtime.api.domain.qa_plan_execution_test_support import (
    TEST_EXECUTION_TARGET,
    TEST_ITEM_ID,
    TEST_ITEM_REF,
)
from yoke_contracts.api.function_call import ActorContext
from yoke_core.domain import (
    machine_qa_case_execution,
    machine_qa_plan_case_execution,
    qa_case_execution,
    qa_plan_execution,
)


def test_client_runner_advances_group_results_and_reuses_them() -> None:
    actor = ActorContext(actor_id="7", session_id="grouped-plan")
    requirements = [
        {
            "requirement_id": 101,
            "item_id": TEST_ITEM_ID,
            "plan_id": 4,
            "case_key": "fresh-first",
            "case_position": 1,
            "baseline_position": 1,
            "host_baseline": "fresh-host",
            "runner_id": "host_control",
        },
        {
            "requirement_id": 102,
            "item_id": TEST_ITEM_ID,
            "plan_id": 4,
            "case_key": "independent-command",
            "case_position": 2,
            "baseline_position": 1,
            "host_baseline": None,
            "runner_id": "worktree_run",
        },
        {
            "requirement_id": 103,
            "item_id": TEST_ITEM_ID,
            "plan_id": 4,
            "case_key": "fresh-later",
            "case_position": 3,
            "baseline_position": 1,
            "host_baseline": "fresh-host",
            "runner_id": "host_control",
        },
        {
            "requirement_id": 104,
            "item_id": TEST_ITEM_ID,
            "plan_id": 4,
            "case_key": "independent-machine",
            "case_position": 4,
            "baseline_position": 1,
            "host_baseline": None,
            "runner_id": "host_control",
        },
    ]
    fresh_results = [
        {
            "requirement_id": requirement_id,
            "verdict": "pass",
            "case_outcome": "passed",
        }
        for requirement_id in (101, 103)
    ]
    function_calls: list[tuple[str, dict]] = []

    def call_plan_function(**kwargs):
        function_calls.append((kwargs["function_id"], kwargs["payload"]))
        if kwargs["function_id"] == "qa.plan_execution.begin":
            return {
                "execution_id": "plan-execution-grouped",
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

    with (
        mock.patch.object(
            qa_plan_execution,
            "_call_plan_function",
            side_effect=call_plan_function,
        ),
        mock.patch.object(
            machine_qa_case_execution,
            "execute_materialized_machine_baseline_group",
            return_value={
                "anchor_requirement_id": 101,
                "baseline_ok": True,
                "requirement_ids": [101, 103],
                "results": fresh_results,
            },
        ) as execute_group,
        mock.patch.object(
            qa_case_execution,
            "execute_case_context",
            return_value={
                "requirement_id": 102,
                "verdict": "pass",
                "case_outcome": "passed",
            },
        ) as execute_independent,
        mock.patch.object(
            machine_qa_plan_case_execution,
            "execute_plan_machine_case",
            return_value={
                "requirement_id": 104,
                "verdict": "pass",
                "case_outcome": "passed",
            },
        ) as execute_independent_machine,
    ):
        result = qa_plan_execution.execute_plan(
            item_ref=TEST_ITEM_REF,
            transition_id="implemented",
            actor=actor,
        )

    assert result["state"] == "passed"
    assert result["executed_count"] == 4
    assert all("baseline_group_results" not in row for row in result["results"])
    execute_group.assert_called_once_with(requirements[0], actor=actor)
    execute_independent.assert_called_once()
    execute_independent_machine.assert_called_once_with(
        requirements[3],
        execution_id="plan-execution-grouped",
        ordinal=3,
        actor=actor,
    )
    advances = [
        payload
        for function_id, payload in function_calls
        if function_id == "qa.plan_execution.advance"
    ]
    assert [payload["requirement_id"] for payload in advances] == [101, 102, 103]
    assert [
        row["requirement_id"] for row in advances[0]["result"]["baseline_group_results"]
    ] == [101, 103]


def test_plan_state_aggregation_preserves_outcome_precedence() -> None:
    ordered = [
        ("passed", {"case_outcome": "passed", "verdict": "pass"}),
        (
            "needs_review",
            {"case_outcome": "needs_review", "verdict": "inconclusive"},
        ),
        (
            "blocked_on_precondition",
            {
                "case_outcome": "blocked_on_precondition",
                "verdict": "inconclusive",
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


def test_fully_blocked_baseline_group_completes_with_distinct_plan_state() -> None:
    actor = ActorContext(actor_id="7", session_id="blocked-group")
    requirements = [
        {
            "requirement_id": requirement_id,
            "item_id": TEST_ITEM_ID,
            "plan_id": 4,
            "case_key": f"blocked-{requirement_id}",
            "case_position": position,
            "baseline_position": 1,
            "host_baseline": "fresh-host",
            "runner_id": "host_control",
        }
        for position, requirement_id in enumerate((151, 152), start=1)
    ]
    blocked_results = [
        {
            "requirement_id": requirement_id,
            "verdict": "inconclusive",
            "case_outcome": "blocked_on_precondition",
        }
        for requirement_id in (151, 152)
    ]
    function_calls: list[tuple[str, dict]] = []

    def call_plan_function(**kwargs):
        function_calls.append((kwargs["function_id"], kwargs["payload"]))
        if kwargs["function_id"] == "qa.plan_execution.begin":
            return {
                "execution_id": "plan-execution-blocked",
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

    with (
        mock.patch.object(
            qa_plan_execution,
            "_call_plan_function",
            side_effect=call_plan_function,
        ),
        mock.patch.object(
            machine_qa_case_execution,
            "execute_materialized_machine_baseline_group",
            return_value={
                "anchor_requirement_id": 151,
                "baseline_ok": False,
                "requirement_ids": [151, 152],
                "results": blocked_results,
            },
        ) as execute_group,
    ):
        result = qa_plan_execution.execute_plan(
            item_ref=TEST_ITEM_REF,
            transition_id="implemented",
            actor=actor,
        )

    assert result["state"] == "blocked_on_precondition"
    assert result["executed_count"] == 2
    assert [row["case_outcome"] for row in result["results"]] == [
        "blocked_on_precondition",
        "blocked_on_precondition",
    ]
    execute_group.assert_called_once_with(requirements[0], actor=actor)
    assert [function_id for function_id, _payload in function_calls] == [
        "qa.plan_execution.begin",
        "qa.plan_execution.heartbeat",
        "qa.plan_execution.advance",
            "qa.plan_execution.heartbeat",
            "qa.plan_execution.advance",
            "qa.plan_review.begin",
            "qa.plan_execution.complete",
    ]


def test_client_runner_resumes_from_durable_baseline_group_results() -> None:
    actor = ActorContext(actor_id="7", session_id="grouped-plan-resume")
    requirements = [
        {
            "requirement_id": requirement_id,
            "item_id": TEST_ITEM_ID,
            "plan_id": 4,
            "case_key": f"fresh-{requirement_id}",
            "case_position": position,
            "baseline_position": 1,
            "host_baseline": "fresh-host",
            "runner_id": "host_control",
        }
        for position, requirement_id in enumerate((201, 202), start=1)
    ]
    group_results = [
        {
            "requirement_id": requirement_id,
            "verdict": "pass",
            "case_outcome": "passed",
        }
        for requirement_id in (201, 202)
    ]
    stored_anchor = {
        "plan_id": 4,
        "case_key": "fresh-201",
        "case_position": 1,
        "baseline_position": 1,
        "host_baseline": "fresh-host",
        **group_results[0],
        "baseline_group_results": group_results,
    }
    function_calls: list[str] = []

    def call_plan_function(**kwargs):
        function_calls.append(kwargs["function_id"])
        if kwargs["function_id"] == "qa.plan_execution.begin":
            return {
                "execution_id": "plan-execution-resumed",
                "item_id": TEST_ITEM_ID,
                "transition_id": "implemented",
                "state": "active",
                "roster_digest": "digest",
                "cursor_ordinal": 1,
                "execution_target": TEST_EXECUTION_TARGET,
                "execution_target_digest": "target-digest",
                "requirements": requirements,
                "results": [{"result": stored_anchor}],
            }
        return {}

    with (
        mock.patch.object(
            qa_plan_execution,
            "_call_plan_function",
            side_effect=call_plan_function,
        ),
        mock.patch.object(
            machine_qa_case_execution,
            "execute_materialized_machine_baseline_group",
        ) as execute_group,
    ):
        result = qa_plan_execution.execute_plan(
            item_ref=TEST_ITEM_REF,
            transition_id="implemented",
            actor=actor,
        )

    execute_group.assert_not_called()
    assert [row["requirement_id"] for row in result["results"]] == [201, 202]
    assert all("baseline_group_results" not in row for row in result["results"])
    assert function_calls == [
        "qa.plan_execution.begin",
            "qa.plan_execution.heartbeat",
            "qa.plan_execution.advance",
            "qa.plan_review.begin",
            "qa.plan_execution.complete",
    ]
