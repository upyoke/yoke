"""Tool-shaped CLI coverage for shared QA case execution."""

from __future__ import annotations

import json
from unittest import mock

from yoke_cli.commands import qa_case
from yoke_core.domain import qa_case_execution_cli, qa_plan_execution_cli


TEST_ITEM_ID = 42
TEST_ITEM_REF = f"YOK-{TEST_ITEM_ID}"


def test_qa_case_run_delegates_to_engine_module() -> None:
    completed = mock.Mock(returncode=7)
    with mock.patch.object(qa_case.subprocess, "run", return_value=completed) as run:
        code = qa_case.qa_case_run(
            [
                "--requirement-id",
                "41",
                "--base-url",
                "https://preview.example",
            ]
        )

    assert code == 7
    command = run.call_args.args[0]
    assert command[1:] == [
        "-m",
        "yoke_core.domain.qa_case_execution_cli",
        "--requirement-id",
        "41",
        "--base-url",
        "https://preview.example",
    ]
    assert run.call_args.kwargs == {"check": False}


def test_engine_cli_executes_case_and_emits_result(capsys) -> None:
    with mock.patch.object(
        qa_case_execution_cli,
        "execute_case",
        return_value={
            "requirement_id": 41,
            "verdict": "pass",
            "run_id": 7,
        },
    ) as execute:
        code = qa_case_execution_cli.run(
            [
                "--requirement-id",
                "41",
                "--base-url",
                "https://preview.example",
            ]
        )

    assert code == 0
    assert json.loads(capsys.readouterr().out)["run_id"] == 7
    execute.assert_called_once_with(
        41,
        base_url="https://preview.example",
        expected_branch=None,
        expected_sha=None,
        timeout_seconds=None,
    )


def test_engine_cli_returns_prerequisite_exit_for_error(capsys) -> None:
    with mock.patch.object(
        qa_case_execution_cli,
        "execute_case",
        return_value={"requirement_id": 41, "verdict": "error"},
    ):
        code = qa_case_execution_cli.run(["--requirement-id", "41"])

    assert code == 2
    assert json.loads(capsys.readouterr().out)["verdict"] == "error"


def test_qa_plan_run_delegates_to_engine_module() -> None:
    completed = mock.Mock(returncode=3)
    with mock.patch.object(qa_case.subprocess, "run", return_value=completed) as run:
        code = qa_case.qa_plan_run(
            [
                "--item",
                TEST_ITEM_REF,
                "--transition",
                "implemented",
            ]
        )

    assert code == 3
    command = run.call_args.args[0]
    assert command[1:] == [
        "-m",
        "yoke_core.domain.qa_plan_execution_cli",
        "--item",
        TEST_ITEM_REF,
        "--transition",
        "implemented",
    ]
    assert run.call_args.kwargs == {"check": False}


def test_plan_engine_cli_reuses_one_session_actor(capsys) -> None:
    with mock.patch.object(
        qa_plan_execution_cli,
        "execute_plan",
        return_value={
            "item_id": TEST_ITEM_ID,
            "transition_id": "implemented",
            "state": "passed",
            "requirement_count": 2,
            "executed_count": 2,
            "results": [],
        },
    ) as execute:
        code = qa_plan_execution_cli.run(
            [
                "--item",
                TEST_ITEM_REF,
                "--transition",
                "implemented",
                "--session-id",
                "plan-session",
            ]
        )

    assert code == 0
    assert json.loads(capsys.readouterr().out)["state"] == "passed"
    assert execute.call_args.kwargs["actor"].session_id == "plan-session"


def test_plan_engine_cli_blocks_on_precondition_and_preserves_state(capsys) -> None:
    with mock.patch.object(
        qa_plan_execution_cli,
        "execute_plan",
        return_value={
            "item_id": TEST_ITEM_ID,
            "transition_id": "implemented",
            "state": "blocked_on_precondition",
            "requirement_count": 2,
            "executed_count": 2,
            "results": [
                {
                    "requirement_id": 41,
                    "case_outcome": "blocked_on_precondition",
                }
            ],
        },
    ):
        code = qa_plan_execution_cli.run(
            [
                "--item",
                TEST_ITEM_REF,
                "--transition",
                "implemented",
                "--session-id",
                "plan-session",
            ]
        )

    assert code == 1
    assert json.loads(capsys.readouterr().out)["state"] == "blocked_on_precondition"
