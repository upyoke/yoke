"""Fail-closed boundaries around client-local ordered-plan side effects."""

from __future__ import annotations

from unittest import mock

import pytest

from runtime.api.domain.qa_plan_execution_test_support import (
    TEST_ITEM_ID,
    TEST_ITEM_REF,
)
from yoke_contracts.api.function_call import ActorContext
from yoke_core.domain import qa_case_execution, qa_plan_execution


ACTOR = ActorContext(actor_id="7", session_id="ordered-failure")
CASE = {
    "requirement_id": 11,
    "item_id": TEST_ITEM_ID,
    "plan_id": 3,
    "case_key": "command",
    "case_position": 1,
    "baseline_position": 1,
    "host_baseline": None,
    "executor_id": "worktree_run",
}


def _begin_result() -> dict:
    return {
        "execution_id": "execution-1",
        "item_id": 42,
        "transition_id": "implemented",
        "state": "active",
        "roster_digest": "digest",
        "cursor_ordinal": 0,
        "requirements": [CASE],
        "results": [],
    }


def test_begin_denial_prevents_every_local_executor_side_effect() -> None:
    with (
        mock.patch.object(
            qa_plan_execution,
            "_call_plan_function",
            side_effect=qa_plan_execution.QaPlanExecutionError("claim denied"),
        ),
        mock.patch.object(
            qa_case_execution,
            "execute_case_context",
        ) as execute,
    ):
        with pytest.raises(
            qa_plan_execution.QaPlanExecutionError,
            match="claim denied",
        ):
            qa_plan_execution.execute_plan(
                item_ref=TEST_ITEM_REF,
                transition_id="implemented",
                actor=ACTOR,
            )
    execute.assert_not_called()


def test_advance_failure_aborts_and_never_reports_the_case_complete() -> None:
    calls: list[str] = []

    def dispatch(**kwargs):
        function_id = kwargs["function_id"]
        calls.append(function_id)
        if function_id == "qa.plan_execution.begin":
            return _begin_result()
        if function_id == "qa.plan_execution.advance":
            raise qa_plan_execution.QaPlanExecutionError(
                "cursor persistence unavailable"
            )
        return {}

    with (
        mock.patch.object(
            qa_plan_execution,
            "_call_plan_function",
            side_effect=dispatch,
        ),
        mock.patch.object(
            qa_case_execution,
            "execute_case_context",
            return_value={
                "requirement_id": 11,
                "executor_id": "worktree_run",
                "verdict": "pass",
                "case_outcome": "passed",
            },
        ),
    ):
        result = qa_plan_execution.execute_plan(
            item_ref=TEST_ITEM_REF,
            transition_id="implemented",
            actor=ACTOR,
        )

    assert result["state"] == "error"
    assert result["results"][0]["case_outcome"] == "error"
    assert "cursor persistence unavailable" in result["results"][0]["error"]
    assert calls == [
        "qa.plan_execution.begin",
        "qa.plan_execution.heartbeat",
        "qa.plan_execution.advance",
        "qa.plan_execution.abort",
    ]


def test_interrupt_aborts_before_propagating_to_the_operator() -> None:
    calls: list[str] = []

    def dispatch(**kwargs):
        function_id = kwargs["function_id"]
        calls.append(function_id)
        if function_id == "qa.plan_execution.begin":
            return _begin_result()
        return {}

    with (
        mock.patch.object(
            qa_plan_execution,
            "_call_plan_function",
            side_effect=dispatch,
        ),
        mock.patch.object(
            qa_case_execution,
            "execute_case_context",
            side_effect=KeyboardInterrupt,
        ),
        pytest.raises(KeyboardInterrupt),
    ):
        qa_plan_execution.execute_plan(
            item_ref=TEST_ITEM_REF,
            transition_id="implemented",
            actor=ACTOR,
        )

    assert calls == [
        "qa.plan_execution.begin",
        "qa.plan_execution.heartbeat",
        "qa.plan_execution.abort",
    ]
