"""A failed capture closes its plan walk so corrected cases can be retried."""

from __future__ import annotations

from unittest import mock

import pytest

from runtime.api.domain.qa_plan_execution_test_support import (
    TEST_EXECUTION_TARGET,
    TEST_ITEM_ID,
    TEST_ITEM_REF,
)
from yoke_contracts.api.function_call import ActorContext
from yoke_core.domain import qa_case_execution, qa_plan_execution


@pytest.mark.parametrize("scope", ["item", "deployment_run"])
@pytest.mark.parametrize(
    ("failed_result", "expected_state"),
    [
        (
            {
                "case_outcome": "failed",
                "verdict": "fail",
                "execution_status": "capture_failed",
            },
            "failed",
        ),
        (
            {
                "case_outcome": "error",
                "verdict": "error",
                "execution_status": "capture_failed",
            },
            "error",
        ),
        (
            {
                "case_outcome": "needs_review",
                "verdict": "pending",
                "execution_status": "capture_failed",
            },
            "failed",
        ),
        ({"case_outcome": "failed", "verdict": "fail"}, "failed"),
    ],
)
def test_failed_capture_closes_execution_and_corrected_roster_enters_review(
    scope: str, failed_result: dict, expected_state: str
) -> None:
    actor = ActorContext(actor_id="7", session_id="capture-session")
    first_case = {
        "requirement_id": 11,
        "plan_id": 3,
        "case_key": "browser",
        "case_position": 1,
        "baseline_position": 1,
        "host_baseline": None,
        "runner_id": "browser_substrate",
    }
    corrected_case = {**first_case, "requirement_id": 12}
    executions = [
        {
            "execution_id": "failed-capture",
            "item_id": TEST_ITEM_ID if scope == "item" else None,
            "deployment_run_id": "run-capture" if scope == "deployment_run" else None,
            "state": "active",
            "cursor_ordinal": 0,
            "execution_target": TEST_EXECUTION_TARGET,
            "requirements": [first_case],
            "results": [],
        },
        {
            "execution_id": "corrected-capture",
            "item_id": TEST_ITEM_ID if scope == "item" else None,
            "deployment_run_id": "run-capture" if scope == "deployment_run" else None,
            "state": "active",
            "cursor_ordinal": 0,
            "execution_target": TEST_EXECUTION_TARGET,
            "requirements": [corrected_case],
            "results": [],
        },
    ]
    calls: list[tuple[str, dict]] = []
    closed = False

    def dispatch(**kwargs):
        nonlocal closed
        function_id = kwargs["function_id"]
        payload = kwargs["payload"]
        calls.append((function_id, payload))
        assert kwargs["actor"] == actor
        if function_id == "qa.plan_execution.begin":
            if len([name for name, _ in calls if name == function_id]) == 2:
                assert closed, "the failed execution must release the live roster"
                return executions[1]
            return executions[0]
        if function_id == "qa.plan_execution.abort":
            assert payload["execution_id"] == "failed-capture"
            closed = True
        if function_id == "qa.plan_review.begin":
            assert payload["execution_id"] == "corrected-capture"
            return {"review_bundle": {"bundle_id": "independent-review"}}
        return {}

    def capture(case, **_kwargs):
        if case["requirement_id"] == 11:
            return {"requirement_id": 11, "qa_run_id": 21, **failed_result}
        return {
            "requirement_id": 12,
            "qa_run_id": 22,
            "case_outcome": "needs_review",
            "verdict": "pending",
            "execution_status": "captured",
        }

    subject = (
        {"public_ref": TEST_ITEM_REF, "transition_id": "implemented"}
        if scope == "item"
        else {
            "deployment_run_id": "run-capture",
            "deployment_stage": "item-qa",
            "deployment_member": TEST_ITEM_REF,
            "project": "yoke",
        }
    )
    with (
        mock.patch.object(
            qa_plan_execution, "_call_plan_function", side_effect=dispatch
        ),
        mock.patch.object(
            qa_case_execution, "execute_case_context", side_effect=capture
        ),
    ):
        failed = qa_plan_execution.execute_plan(**subject, actor=actor)
        corrected = qa_plan_execution.execute_plan(**subject, actor=actor)

    assert failed["state"] == expected_state
    assert failed["review_bundle"] is None
    assert failed["results"][0]["qa_run_id"] == 21
    assert "rerun yoke qa plan run" in failed["recovery"]
    assert corrected["state"] == "awaiting_agent_review"
    assert corrected["review_status"] == "pending"
    assert corrected["review_bundle"]["bundle_id"] == "independent-review"
    assert [name for name, _ in calls].count("qa.plan_execution.abort") == 1
    assert [name for name, _ in calls].count("qa.plan_review.begin") == 1
