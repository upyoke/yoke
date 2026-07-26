"""Tool-shaped CLI coverage for shared QA case execution."""

from __future__ import annotations

import json
from unittest import mock

from yoke_cli.commands import qa_case
from yoke_core.domain import qa_case_execution_cli


def test_qa_case_run_delegates_to_engine_module() -> None:
    completed = mock.Mock(returncode=7)
    with mock.patch.object(qa_case.subprocess, "run", return_value=completed) as run:
        code = qa_case.qa_case_run([
            "--requirement-id", "41",
            "--base-url", "https://preview.example",
        ])

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
        code = qa_case_execution_cli.run([
            "--requirement-id", "41",
            "--base-url", "https://preview.example",
        ])

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
