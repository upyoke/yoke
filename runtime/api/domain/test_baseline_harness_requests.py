"""Golden capture and mission restore require real harness authentication."""

from __future__ import annotations

import json
import base64
import shlex
import subprocess
from types import SimpleNamespace

import pytest

from yoke_contracts.machine_qa_execution import GUI_SESSION_CONTEXT
from yoke_harness.baseline_harness_requests import PROBE_PROMPT, harness_request
from yoke_harness.ssh_linux_baseline import capture_linux_golden, prove_linux_probes
from yoke_harness.ssh_mac_baseline_probes import (
    prove_declared_probes,
    prove_probes_document,
)
from yoke_harness.ssh_mac_golden_capture import capture_golden_baseline
from yoke_harness import ssh_mac_gui_session
from yoke_harness.ssh_mac_transport import SshMacTransport
from yoke_harness.ssh_linux_host_operations import SshLinuxHostOperations


def _document(program):
    return json.dumps(
        {
            "probes": [
                {
                    "name": "signed-in harness",
                    "argv": [f"/home/test/.local/bin/{program}", "status"],
                    "expect_output_contains": "Logged in",
                }
            ]
        }
    )


def _events(*events):
    return "\n".join(json.dumps(event) for event in events)


def _response(program):
    if program == "codex":
        return _events(
            {"type": "item.completed", "item": {"type": "agent_message", "text": "OK"}},
            {"type": "turn.completed", "usage": {"output_tokens": 1}},
        )
    return _events(
        {"type": "result", "subtype": "success", "is_error": False, "result": "OK"}
    )


class _Control:
    golden_baseline_path = "/srv/golden"

    def __init__(self, program, *, stdout=None, returncode=0):
        self.document = _document(program)
        self.result = SimpleNamespace(
            returncode=returncode,
            stdout=_response(program) if stdout is None else stdout,
            stderr="private-account@example.com expired OAuth token",
        )
        self.calls = []

    def run_command(self, argv, *, timeout, **kwargs):
        self.calls.append((list(argv), timeout, kwargs))
        return self.result

    def read_remote_text(self, path):
        assert path == self.golden_baseline_path + ".probes"
        return self.document


@pytest.mark.parametrize("program", ["claude", "codex", "cursor-agent", "agent"])
@pytest.mark.parametrize("platform", ["macos", "linux"])
def test_status_sidecars_execute_a_real_request_without_recording_identity(
    program, platform
):
    control = _Control(program)
    result = (
        prove_probes_document(control, control.document)
        if platform == "macos"
        else prove_linux_probes(control, control.document)
    )
    assert result.ok
    argv, timeout, kwargs = control.calls[0]
    assert argv == list(harness_request([argv[0]]).argv)
    assert argv[-1] == PROBE_PROMPT
    assert "status" not in argv
    assert timeout == 120
    assert kwargs == (
        {"required_session_context": GUI_SESSION_CONTEXT} if platform == "macos" else {}
    )
    assert "private-account" not in repr(result.evidence)


@pytest.mark.parametrize("platform", ["macos", "linux"])
def test_real_transport_preserves_empty_tool_option_in_claude_probe(
    monkeypatch, platform
):
    commands = []

    def run(command, **kwargs):
        if command.startswith("if /bin/test -f "):
            stdout = "0\n"
        elif command.startswith("/usr/bin/base64 < "):
            output = _response("claude") if command.endswith(".stdout") else ""
            stdout = base64.b64encode(output.encode()).decode()
        elif command.startswith("/bin/rm -f "):
            stdout = ""
        else:
            commands.append(command)
            stdout = _response("claude")
        return subprocess.CompletedProcess(command, 0, stdout, "")

    def open_window(_run, *, command, **kwargs):
        commands.append(command)
        return SimpleNamespace(window_id=445)

    monkeypatch.setattr(ssh_mac_gui_session, "open_terminal_app_window", open_window)
    monkeypatch.setattr(
        ssh_mac_gui_session, "close_terminal_app_window", lambda *a, **k: None
    )
    transport = SshMacTransport if platform == "macos" else SshLinuxHostOperations
    control = transport.__new__(transport)
    control._run = run
    document = _document("claude")
    result = (
        prove_probes_document(control, document)
        if platform == "macos"
        else prove_linux_probes(control, document)
    )

    assert result.ok, result.evidence
    request = harness_request(["/home/test/.local/bin/claude"])
    assert len(commands) == 1
    assert shlex.join(request.argv) in commands[0]
    if platform == "linux":
        assert shlex.split(commands[0]) == list(request.argv)


@pytest.mark.parametrize("transport", [SshMacTransport, SshLinuxHostOperations])
@pytest.mark.parametrize("argv", [[], [""], ["", "--tools", ""]])
def test_host_command_still_refuses_an_empty_executable(transport, argv):
    control = transport.__new__(transport)
    with pytest.raises(ValueError, match="command requires"):
        control.run_command(argv)


@pytest.mark.parametrize(
    "program,login",
    [
        ("claude", "claude auth login"),
        ("codex", "codex login"),
        ("cursor-agent", "cursor-agent login"),
        ("agent", "agent login"),
    ],
)
@pytest.mark.parametrize("platform", ["macos", "linux"])
def test_expired_session_refuses_with_the_exact_harness_sign_in_command(
    program, login, platform
):
    control = _Control(program, returncode=1, stdout="OAuth refresh failed")
    result = (
        prove_declared_probes(control)
        if platform == "macos"
        else prove_linux_probes(control, control.document)
    )
    assert not result.ok
    assert result.error_code == "baseline_probe_failed"
    assert f"/home/test/.local/bin/{login}" in result.evidence["reason"]
    assert "Re-sign-in" in result.evidence["reason"]
    assert "private-account" not in repr(result.evidence)


@pytest.mark.parametrize("program", ["claude", "codex", "cursor-agent", "agent"])
def test_zero_exit_login_status_is_not_a_native_request_response(program):
    control = _Control(program, stdout="Logged in")
    result = prove_linux_probes(control, control.document)
    assert not result.ok
    assert result.evidence["probes"][0]["cause"] == "probe_reply_unanswered"


@pytest.mark.parametrize(
    "program,trace",
    [
        (
            "claude",
            {"type": "assistant", "message": {"content": [{"type": "tool_use"}]}},
        ),
        ("codex", {"type": "item.started", "item": {"type": "command_execution"}}),
        ("cursor-agent", {"type": "tool_call", "subtype": "started"}),
    ],
)
def test_a_request_that_uses_tools_cannot_pass(program, trace):
    control = _Control(program, stdout=_events(trace) + "\n" + _response(program))
    assert not prove_linux_probes(control, control.document).ok


@pytest.mark.parametrize(
    "stdout",
    [
        "",
        "not json",
        "[]",
        '{"type":"item.completed","item":"bad"}',
        '{"type":"assistant","message":null}',
        _events({"type": "result", "subtype": "error", "result": "OK"}),
        _events(
            {"type": "result", "subtype": "success", "is_error": True, "result": "OK"}
        ),
        _events({"type": "result", "subtype": "success", "result": "Logged in"}),
        _events(
            {"type": "item.completed", "item": {"type": "agent_message", "text": "OK"}}
        ),
    ],
)
def test_missing_failed_or_malformed_native_completion_is_refused(stdout):
    request = harness_request(["/bin/codex"])
    assert not request.answered(stdout)


@pytest.mark.parametrize("platform", ["macos", "linux"])
def test_capture_does_not_archive_or_seal_an_expired_session(platform):
    control = _Control("claude", returncode=1)
    # No archive or upload method: a failed request must return before either.
    result = (
        capture_linux_golden(control, "/srv/new-golden", None)
        if platform == "linux"
        else capture_golden_baseline(control, destination="/srv/new-golden")
    )
    assert not result.ok
    assert len(control.calls) == 1
    evidence = (
        result.evidence if platform == "linux" else result.evidence["user_equivalence"]
    )
    assert "Claude" in evidence["reason"]


def test_non_harness_service_probe_keeps_its_declared_argv_and_expectation():
    assert harness_request(["/bin/systemctl", "--user", "is-active", "relay"]) is None


def test_timeout_refuses_without_a_traceback_or_macos_repair_on_linux():
    control = _Control("codex")

    def timeout(*args, **kwargs):
        raise TimeoutError("private-account@example.com")

    control.run_command = timeout
    result = prove_linux_probes(control, control.document)
    assert not result.ok
    assert "Codex real request did not return" in result.evidence["reason"]
    assert "/home/test/.local/bin/codex login" in result.evidence["reason"]
    assert "Terminal.app" not in repr(result.evidence)
    assert "private-account" not in repr(result.evidence)


def test_request_adapters_limit_tools_without_permission_bypass():
    claude = harness_request(["/bin/claude"]).argv
    # Bare mode never reads OAuth/keychain credentials; safe mode retains them.
    assert "--safe-mode" in claude and "--bare" not in claude
    assert claude[claude.index("--tools") + 1] == ""
    assert "--strict-mcp-config" in claude
    codex = harness_request(["/bin/codex"]).argv
    assert "--ignore-user-config" in codex
    assert codex[codex.index("--disable") + 1] == "shell_tool"
    cursor = harness_request(["/bin/cursor-agent"]).argv
    assert cursor[cursor.index("--mode") + 1] == "ask"
