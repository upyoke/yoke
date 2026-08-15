"""A plan run states which case failed and why, not only in its JSON.

``yoke qa case run`` restates its verdict on stderr so a reader of the
terminal knows what happened without parsing stdout. A plan run executes
many cases and can end on one of them failing to dispatch at all; that
reason belongs on stderr too, or the operator sees an exit code and a
JSON blob and re-runs the command by hand to find out why.
"""

from __future__ import annotations

import json
from unittest import mock

from yoke_core.domain import qa_plan_execution_cli

TEST_ITEM_ID = 42
TEST_ITEM_REF = f"YOK-{TEST_ITEM_ID}"
DISPATCH_ERROR = "no local checkout is mapped for project 'yoke'"


def _plan_result(state: str, results: list[dict]) -> dict:
    return {
        "execution_id": "exec-1",
        "item_id": TEST_ITEM_ID,
        "transition_id": "implemented",
        "state": state,
        "requirement_count": 2,
        "executed_count": len(results),
        "results": results,
    }


def _run_plan_cli() -> int:
    return qa_plan_execution_cli.run(
        [
            "--item",
            TEST_ITEM_REF,
            "--transition",
            "implemented",
            "--session-id",
            "plan-session",
        ]
    )


def test_plan_cli_names_the_case_that_failed_to_dispatch(capsys) -> None:
    result = _plan_result(
        "error",
        [
            {"requirement_id": 40, "case_key": "quick", "verdict": "pass"},
            {
                "requirement_id": 41,
                "case_key": "full",
                "case_outcome": "error",
                "error": DISPATCH_ERROR,
            },
        ],
    )
    with mock.patch.object(
        qa_plan_execution_cli,
        "execute_plan",
        return_value=result,
    ):
        code = _run_plan_cli()

    captured = capsys.readouterr()
    assert code == 2
    assert json.loads(captured.out)["state"] == "error"
    assert "requirement=41" in captured.err
    assert "case=full" in captured.err
    assert DISPATCH_ERROR in captured.err


def test_plan_cli_names_a_failing_verdict_without_an_error(capsys) -> None:
    result = _plan_result(
        "failed",
        [
            {
                "requirement_id": 41,
                "case_key": "full",
                "case_outcome": "failed",
                "verdict": "fail",
                "exit_code": 1,
            },
        ],
    )
    with mock.patch.object(
        qa_plan_execution_cli,
        "execute_plan",
        return_value=result,
    ):
        code = _run_plan_cli()

    captured = capsys.readouterr()
    assert code == 1
    assert "requirement=41" in captured.err
    assert "outcome=failed" in captured.err


def test_plan_cli_stays_quiet_when_every_case_passed(capsys) -> None:
    result = _plan_result(
        "passed",
        [{"requirement_id": 41, "case_key": "full", "verdict": "pass"}],
    )
    with mock.patch.object(
        qa_plan_execution_cli,
        "execute_plan",
        return_value=result,
    ):
        code = _run_plan_cli()

    captured = capsys.readouterr()
    assert code == 0
    assert captured.err == ""
    assert json.loads(captured.out)["state"] == "passed"
