"""PreToolUse gating for tool calls the relay approves on a native's behalf."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from yoke_harness.session_relay_acp_tool_gate import (
    ToolGateDecision,
    evaluate_native_command,
    permission_request_command,
)
from yoke_harness.session_relay_cursor_acp_terminal import (
    CursorAcpTerminalRegistry,
    ToolCallRefused,
    respond_to_agent_request,
)


CURSOR_DENY = json.dumps(
    {
        "permission": "deny",
        "user_message": "destructive git verb threatens local state",
        "agent_message": "destructive git verb threatens local state",
    }
)
CLAUDE_DENY = json.dumps(
    {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": "worktree write authority missing",
        }
    }
)


def _runner(stdout: str, returncode: int = 0, calls: list | None = None):
    def run(command, **kwargs):
        if calls is not None:
            calls.append((command, kwargs))
        return SimpleNamespace(returncode=returncode, stdout=stdout)

    return run


def test_gate_runs_the_installed_chain_with_the_payload_guards_read(tmp_path: Path):
    calls: list = []

    decision = evaluate_native_command(
        ["git", "reset", "--hard"],
        cwd=tmp_path,
        environ={"YOKE_EXECUTOR": "cursor"},
        command_runner=_runner("", calls=calls),
    )

    assert decision == ToolGateDecision(True)
    command, options = calls[0]
    assert command == ["yoke", "hook", "evaluate", "PreToolUse"]
    payload = json.loads(options["input"])
    assert payload["hook_event_name"] == "PreToolUse"
    assert payload["tool_name"] == "Bash"
    assert payload["tool_input"]["command"] == "git reset --hard"
    assert payload["cwd"] == str(tmp_path)


def test_a_cursor_shaped_denial_refuses_even_on_exit_zero(tmp_path: Path):
    # Cursor reads its verdict on exit 0, so the exit code alone cannot decide.
    decision = evaluate_native_command(
        ["git", "clean", "-fdx"],
        cwd=tmp_path,
        environ={},
        command_runner=_runner(CURSOR_DENY, returncode=0),
    )

    assert decision.allowed is False
    assert "destructive git verb" in decision.reason


def test_a_hook_specific_denial_refuses_and_carries_its_reason(tmp_path: Path):
    decision = evaluate_native_command(
        ["rm", "-rf", "src"],
        cwd=tmp_path,
        environ={},
        command_runner=_runner(CLAUDE_DENY, returncode=2),
    )

    assert decision.allowed is False
    assert decision.reason == "worktree write authority missing"


def test_an_unavailable_chain_fails_closed(tmp_path: Path):
    def explode(*_args, **_kwargs):
        raise OSError("yoke is not installed")

    decision = evaluate_native_command(
        ["ls"], cwd=tmp_path, environ={}, command_runner=explode
    )

    assert decision.allowed is False
    assert "guard chain unavailable" in decision.reason


def test_a_refused_terminal_never_spawns_a_process(tmp_path: Path):
    spawns: list = []
    registry = CursorAcpTerminalRegistry(
        tmp_path,
        environ={},
        process_factory=lambda *args, **kwargs: spawns.append((args, kwargs)),
        tool_gate=lambda *_a, **_k: ToolGateDecision(False, "refused by guard chain"),
    )

    response = respond_to_agent_request(
        registry,
        {
            "id": 7,
            "method": "terminal/create",
            "params": {"command": "git", "args": ["reset", "--hard"]},
        },
    )

    assert spawns == []
    assert response["error"]["message"] == "refused by guard chain"


def test_an_allowed_terminal_still_reaches_the_process_factory(tmp_path: Path):
    spawns: list = []

    def spawn(command, **kwargs):
        spawns.append(command)
        return SimpleNamespace(
            stdout=SimpleNamespace(read=lambda _size: b""),
            poll=lambda: 0,
            wait=lambda timeout=None: 0,
            terminate=lambda: None,
        )

    registry = CursorAcpTerminalRegistry(
        tmp_path,
        environ={},
        process_factory=spawn,
        tool_gate=lambda *_a, **_k: ToolGateDecision(True),
    )

    result = registry.create({"command": "git", "args": ["status"]})

    assert spawns == [["git", "status"]]
    assert "terminalId" in result


def test_a_refused_permission_request_is_cancelled_not_approved(tmp_path: Path):
    registry = CursorAcpTerminalRegistry(
        tmp_path,
        environ={},
        tool_gate=lambda *_a, **_k: ToolGateDecision(False, "refused"),
    )

    response = respond_to_agent_request(
        registry,
        {
            "id": 3,
            "method": "session/request_permission",
            "params": {
                "toolCall": {"rawInput": {"command": "git push --force"}},
                "options": [{"kind": "allow_once", "optionId": "yes"}],
            },
        },
    )

    assert response["result"] == {"outcome": {"outcome": "cancelled"}}


def test_a_permission_request_naming_no_command_keeps_allow_once(tmp_path: Path):
    refusals: list = []
    registry = CursorAcpTerminalRegistry(
        tmp_path,
        environ={},
        tool_gate=lambda *_a, **_k: refusals.append(_a) or ToolGateDecision(False),
    )

    response = respond_to_agent_request(
        registry,
        {
            "id": 4,
            "method": "session/request_permission",
            "params": {
                "toolCall": {"rawInput": {"path": "README.md"}},
                "options": [{"kind": "allow_once", "optionId": "yes"}],
            },
        },
    )

    assert response["result"] == {"outcome": {"outcome": "selected", "optionId": "yes"}}
    assert refusals == []


def test_permission_request_commands_are_read_as_argv():
    assert permission_request_command(
        {"toolCall": {"rawInput": {"command": ["git", "status"]}}}
    ) == ["git", "status"]
    assert permission_request_command(
        {"toolCall": {"rawInput": {"command": "git commit -m 'x y'"}}}
    ) == ["git", "commit", "-m", "x y"]
    assert permission_request_command({"toolCall": {"rawInput": {}}}) is None
    assert permission_request_command({}) is None


def test_terminate_and_release_do_not_re_evaluate_the_gate(tmp_path: Path):
    gate_calls: list = []
    registry = CursorAcpTerminalRegistry(
        tmp_path,
        environ={},
        process_factory=lambda *_a, **_k: SimpleNamespace(
            stdout=SimpleNamespace(read=lambda _size: b""),
            poll=lambda: 0,
            wait=lambda timeout=None: 0,
            terminate=lambda: None,
        ),
        tool_gate=lambda *a, **_k: gate_calls.append(a) or ToolGateDecision(True),
    )
    terminal_id = registry.create({"command": "git", "args": ["status"]})["terminalId"]

    registry.output({"terminalId": terminal_id})
    registry.release({"terminalId": terminal_id})

    assert len(gate_calls) == 1


def test_a_refusal_raised_from_create_is_not_a_malformed_request(tmp_path: Path):
    registry = CursorAcpTerminalRegistry(
        tmp_path,
        environ={},
        tool_gate=lambda *_a, **_k: ToolGateDecision(False, "denied"),
    )

    try:
        registry.create({"command": "git", "args": ["status"]})
    except ToolCallRefused as refusal:
        assert str(refusal) == "denied"
    else:  # pragma: no cover - the gate must refuse
        raise AssertionError("a refused command was allowed to spawn")
