"""Tool-shaped CLI coverage for shared QA case execution."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from unittest import mock

import pytest

from yoke_cli.commands import qa_case
from yoke_core.domain import qa_case_execution_cli, qa_plan_execution_cli


TEST_ITEM_ID = 42
TEST_ITEM_REF = f"YOK-{TEST_ITEM_ID}"


def test_qa_case_run_delegates_to_engine_module() -> None:
    process = mock.Mock()
    process.wait.return_value = 7
    with (
        mock.patch.object(
            qa_case, "build_actor", return_value=mock.Mock(session_id="case-session"),
        ),
        mock.patch.object(qa_case.subprocess, "Popen", return_value=process) as popen,
    ):
        code = qa_case.qa_case_run(
            [
                "--requirement-id",
                "41",
                "--base-url",
                "https://preview.example",
            ]
        )

    assert code == 7
    command = popen.call_args.args[0]
    assert command[1:] == [
        "-m",
        "yoke_core.domain.qa_case_execution_cli",
        "--requirement-id",
        "41",
        "--base-url",
        "https://preview.example",
        "--session-id",
        "case-session",
    ]
    assert popen.call_args.kwargs["start_new_session"] is True
    assert popen.call_args.kwargs["env"]["YOKE_SESSION_ID"] == "case-session"


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
                "--session-id",
                "engine-session",
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
        actor=mock.ANY,
    )
    assert execute.call_args.kwargs["actor"].session_id == "engine-session"
def test_qa_case_run_preserves_explicit_session_override() -> None:
    process = mock.Mock()
    process.wait.return_value = 0
    with (
        mock.patch.object(qa_case, "build_actor") as build_actor,
        mock.patch.object(qa_case.subprocess, "Popen", return_value=process) as popen,
    ):
        assert qa_case.qa_case_run(
            ["--requirement-id", "41", "--session-id", "operator-session"]
        ) == 0

    build_actor.assert_not_called()
    assert popen.call_args.args[0][-2:] == ["--session-id", "operator-session"]
    assert popen.call_args.kwargs["env"]["YOKE_SESSION_ID"] == "operator-session"
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
    process = mock.Mock()
    process.wait.return_value = 3
    with (
        mock.patch.object(
            qa_case, "build_actor", return_value=mock.Mock(session_id="plan-session"),
        ),
        mock.patch.object(qa_case.subprocess, "Popen", return_value=process) as popen,
    ):
        code = qa_case.qa_plan_run(
            [
                "--item",
                TEST_ITEM_REF,
                "--transition",
                "implemented",
            ]
        )

    assert code == 3
    command = popen.call_args.args[0]
    assert command[1:] == [
        "-m",
        "yoke_core.domain.qa_plan_execution_cli",
        "--item",
        TEST_ITEM_REF,
        "--transition",
        "implemented",
        "--session-id",
        "plan-session",
    ]
    assert popen.call_args.kwargs["start_new_session"] is True
    assert popen.call_args.kwargs["env"]["YOKE_SESSION_ID"] == "plan-session"


@pytest.mark.parametrize(
    ("runner", "args"),
    (
        (qa_case.qa_case_run, ["--requirement-id", "41"]),
        (qa_case.qa_plan_run, ["--item", TEST_ITEM_REF, "--transition", "done"]),
    ),
)
def test_qa_runner_waits_for_interrupt_cleanup_and_returns_130(
    runner,
    args: list[str],
) -> None:
    process = mock.Mock()
    process.wait.side_effect = [KeyboardInterrupt, 0]
    process.poll.return_value = None
    previous_handler = object()
    with (
        mock.patch.object(qa_case.subprocess, "Popen", return_value=process),
        mock.patch.object(
            qa_case.signal,
            "signal",
            side_effect=[previous_handler, previous_handler],
        ) as set_signal,
    ):
        code = runner(args)

    assert code == 130
    assert process.wait.call_count == 2
    process.send_signal.assert_called_once_with(signal.SIGINT)
    assert set_signal.call_args_list == [
        mock.call(signal.SIGINT, signal.SIG_IGN),
        mock.call(signal.SIGINT, previous_handler),
    ]


@pytest.mark.parametrize(
    ("runner_name", "module_name"),
    (
        ("qa_case_run", "qa_case_execution_cli"),
        ("qa_plan_run", "qa_plan_execution_cli"),
    ),
)
def test_qa_runner_preserves_child_interrupt_cleanup(
    tmp_path,
    runner_name: str,
    module_name: str,
) -> None:
    fake_package = tmp_path / "yoke_core" / "domain"
    fake_package.mkdir(parents=True)
    (fake_package.parent / "__init__.py").write_text("")
    (fake_package / "__init__.py").write_text("")
    (fake_package / f"{module_name}.py").write_text(
        """
import os
from pathlib import Path
import time

Path(os.environ["QA_INTERRUPT_READY"]).write_text("ready")
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    time.sleep(0.4)
    Path(os.environ["QA_INTERRUPT_CLEANUP"]).write_text("released")
    raise
""".lstrip()
    )
    ready = tmp_path / "ready"
    cleanup = tmp_path / "cleanup"
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(
        [str(tmp_path), environment.get("PYTHONPATH", "")]
    )
    environment["QA_INTERRUPT_READY"] = str(ready)
    environment["QA_INTERRUPT_CLEANUP"] = str(cleanup)
    wrapper = subprocess.Popen(
        [
            sys.executable,
            "-c",
            (
                f"from yoke_cli.commands.qa_case import {runner_name};"
                f"raise SystemExit({runner_name}([]))"
            ),
        ],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    # Generous deadlines: this asserts the interrupt path COMPLETES (a hang
    # never finishes), not that it is fast. Concurrent full-suite gates on
    # one machine starve niced test processes for several seconds at a
    # time, and a tight budget here reads as a cleanup regression.
    deadline = time.monotonic() + 30
    try:
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ready.exists()
        os.kill(wrapper.pid, signal.SIGINT)
        wrapper.communicate(timeout=30)
    finally:
        if wrapper.poll() is None:
            wrapper.kill()
            wrapper.wait()

    assert wrapper.returncode == 130
    assert cleanup.read_text() == "released"


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


def test_plan_engine_cli_accepts_deployment_run_subject(capsys) -> None:
    with mock.patch.object(
        qa_plan_execution_cli,
        "execute_plan",
        return_value={
            "item_id": None,
            "deployment_run_id": "run-20260728-901",
            "transition_id": None,
            "state": "passed",
            "requirement_count": 1,
            "executed_count": 1,
            "results": [],
        },
    ) as execute:
        code = qa_plan_execution_cli.run(
            [
                "--deployment-run-id",
                "run-20260728-901",
                "--plan",
                "installer-campaign",
                "--project",
                "yoke",
                "--session-id",
                "deployment-plan-session",
            ]
        )

    assert code == 0
    assert (
        json.loads(capsys.readouterr().out)["deployment_run_id"] == "run-20260728-901"
    )
    assert execute.call_args.kwargs["item_ref"] is None
    assert execute.call_args.kwargs["deployment_run_id"] == "run-20260728-901"
    assert execute.call_args.kwargs["plan"] == "installer-campaign"


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
