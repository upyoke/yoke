"""Lease-routed exploratory mission CLI behavior."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest import mock

import pytest

from yoke_cli.commands import qa_case
from yoke_cli.commands.qa_case import qa_mission_host_command
from yoke_cli.commands.tool_shaped import resolve_tool_shaped
from yoke_core.domain import agent_mission_host_command_cli


def test_mission_host_command_token_routes_to_detached_adapter() -> None:
    resolved = resolve_tool_shaped(
        [
            "qa", "mission", "host-command", "--item-id", "42",
            "--execution-id", "exec-1", "--requirement-id", "9",
            "--", "whoami",
        ]
    )
    assert resolved is not None
    adapter, rest = resolved
    assert adapter is qa_mission_host_command
    assert rest[-2:] == ["--", "whoami"]


def test_mission_host_command_pins_session_without_mutating_python_argv() -> None:
    requested = [
        "--item-id", "42",
        "--execution-id", "exec-1",
        "--requirement-id", "9",
        "--", "/usr/bin/python3", "-c",
        "import sys,json; print(json.dumps(sys.argv))",
    ]
    process = mock.Mock()
    process.wait.return_value = 0
    with mock.patch.object(
        qa_case, "build_actor", return_value=mock.Mock(session_id="mission-session")
    ), mock.patch.object(
        qa_case.subprocess, "Popen", return_value=process
    ) as popen:
        assert qa_mission_host_command(requested) == 0

    assert popen.call_args.args[0][3:] == requested
    assert popen.call_args.kwargs["env"]["YOKE_SESSION_ID"] == "mission-session"


def test_mission_host_command_rejects_injected_remote_argument() -> None:
    requested = [
        "--item-id", "42", "--execution-id", "exec-1",
        "--requirement-id", "9", "--", "/bin/echo", "probe-alive",
    ]
    injected = [*requested, "--session-id", "leaked-session"]
    with mock.patch.object(
        qa_case,
        "_pin_execution_session",
        return_value=(injected, "leaked-session"),
    ), mock.patch.object(qa_case.subprocess, "Popen") as popen, pytest.raises(
        RuntimeError, match="forwarded '--session-id'"
    ):
        qa_mission_host_command(requested)

    popen.assert_not_called()


def test_host_command_forwards_python_probe_argv_exactly(capsys) -> None:
    response = SimpleNamespace(
        success=True,
        error=None,
        result={"execution": {"operation": "plan_case"}},
    )
    completed = {
        "exit_code": 0,
        "stdout": "[]\n",
        "stderr": "",
        "execution_context": "ssh",
        "session_context_degraded_reason": None,
        "session_context_error_code": None,
    }
    command = [
        "/usr/bin/python3",
        "-c",
        "import sys,json; print(json.dumps(sys.argv))",
    ]
    with mock.patch(
        "yoke_core.domain.qa_composed_dispatch.call_qa_function",
        return_value=response,
    ), mock.patch(
        "yoke_core.domain.ssh_mac_host_control.register_ssh_mac_host_control",
    ), mock.patch(
        "yoke_core.domain.machine_qa_local_execution."
        "execute_agent_mission_host_command",
        return_value=completed,
    ) as execute:
        code = agent_mission_host_command_cli.run(
            [
                "--item-id", "42", "--execution-id", "exec-1",
                "--requirement-id", "9", "--", *command,
            ]
        )

    assert code == 0
    assert json.loads(capsys.readouterr().out)["command_arity"] == len(command)
    assert execute.call_args.kwargs["argv"] == command


def test_host_command_result_does_not_echo_sensitive_argv(capsys) -> None:
    response = SimpleNamespace(
        success=True,
        error=None,
        result={"execution": {"operation": "plan_case"}},
    )
    completed = {
        "exit_code": 0,
        "stdout": "signed in\n",
        "stderr": "",
        "execution_context": "ssh",
        "session_context_degraded_reason": None,
        "session_context_error_code": None,
    }
    command = ["credential-cli", "--token", "top-secret"]
    with mock.patch(
        "yoke_core.domain.qa_composed_dispatch.call_qa_function",
        return_value=response,
    ), mock.patch(
        "yoke_core.domain.ssh_mac_host_control.register_ssh_mac_host_control",
    ), mock.patch(
        "yoke_core.domain.machine_qa_local_execution."
        "execute_agent_mission_host_command",
        return_value=completed,
    ) as execute:
        code = agent_mission_host_command_cli.run(
            [
                "--item-id", "42",
                "--execution-id", "exec-1",
                "--requirement-id", "9",
                "--", *command,
            ]
        )

    captured = capsys.readouterr()
    assert code == 0
    payload = json.loads(captured.out)
    assert payload["command_arity"] == len(command)
    assert "argv" not in payload
    assert "top-secret" not in captured.out
    assert "top-secret" not in captured.err
    assert execute.call_args.kwargs["argv"] == command
