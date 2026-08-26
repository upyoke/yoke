"""Every launched session runs with its harness permission bypass engaged.

A launched session has no operator to answer an approval prompt, so the
create and wake routes of all three harness families must carry the bypass
posture their native expects — and the one native gate that can still refuse
it must name its own recovery step.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_contracts.executor_labels import CANONICAL_HARNESS_IDS
from yoke_contracts.session_control.launch_permission_bypass import (
    CLAUDE_BYPASS_DISCLAIMER_RECOVERY,
    CURSOR_ACP_BYPASS_IS_RELAY_ANSWERED,
    cli_bypass_arguments,
)
from yoke_cli.commands.adapters.session_control_native_diagnostic_output import (
    native_diagnostic_fields,
)
from yoke_harness import session_relay_codex_app_server as app_module
from yoke_harness import session_relay_codex_cli as codex_cli_module
from yoke_harness import session_relay_cursor_cli as cursor_cli_module
from yoke_harness.session_relay_claude import ClaudeNativeInvocation
from yoke_harness.session_relay_codex import CodexNativeRequest
from yoke_harness.session_relay_native_diagnostics import (
    PERMISSION_BYPASS_UNACCEPTED,
    classify_native_failure,
)

from runtime.harness.test_session_relay_codex_app_server_wake import FakeAppClient
from runtime.harness.test_session_relay_codex_cli_process import _request
from runtime.harness.test_session_relay_cursor_native import (
    RunningProcess,
    SESSION_ID,
    _wake_request,
)


def _claude_invocation(*, resume: bool) -> ClaudeNativeInvocation:
    return ClaudeNativeInvocation(
        "/opt/claude",
        Path("/project"),
        "12345678-1234-4234-8234-123456789abc",
        "2.1.246",
        "instruction",
        resume=resume,
    )


def test_every_harness_family_declares_its_bypass_arguments() -> None:
    for harness_id in CANONICAL_HARNESS_IDS:
        assert cli_bypass_arguments(harness_id)
    with pytest.raises(ValueError):
        cli_bypass_arguments("borrowed-harness")


@pytest.mark.parametrize("resume", [False, True])
def test_claude_create_and_resume_both_skip_permissions(resume: bool) -> None:
    assert "--dangerously-skip-permissions" in _claude_invocation(resume=resume).argv


def test_codex_exec_bypasses_approvals_and_sandbox_on_create_and_resume(
    tmp_path: Path,
) -> None:
    command = codex_cli_module._base_command("/opt/codex", _request(tmp_path))

    # The resume route appends to this same base, so one assertion covers both.
    assert "--dangerously-bypass-approvals-and-sandbox" in command


def test_codex_app_server_wake_resumes_a_thread_unattended(
    monkeypatch,
    tmp_path: Path,
) -> None:
    client = FakeAppClient("notLoaded")
    monkeypatch.setattr(
        app_module.CodexAppServerTransport, "_client", lambda *_: client
    )
    request = CodexNativeRequest(
        job_kind="wake",
        job_id="wake-1",
        surface="codex-desktop",
        surface_version="0.149.0",
        checkout=tmp_path,
        requested_model=None,
        presentation=None,
        target_liveness="idle",
        target_session_id="native-1",
        wake_mode="idle_timeout",
        instruction_id="wake:1",
        native_instruction="instruction",
        target_thread_id="native-1",
    )

    outcome = app_module.CodexAppServerTransport(worker=True).wake(request)

    assert outcome.state == "accepted"
    resumed = next(params for method, params in client.calls if method == "thread/resume")
    assert resumed["approvalPolicy"] == "never"
    assert resumed["sandbox"] == "danger-full-access"


def test_cursor_cli_wake_auto_approves_commands(monkeypatch, tmp_path: Path) -> None:
    spawns: list[list[str]] = []
    monkeypatch.setattr(
        cursor_cli_module, "resolve_native_cli", lambda _name: "/opt/cursor-agent"
    )

    def spawn(command, **_kwargs):
        spawns.append(command)
        return RunningProcess()

    cursor_cli_module.CursorCliTransport(process_factory=spawn).resume_chat(
        _wake_request(tmp_path)
    )

    assert SESSION_ID in spawns[0]
    assert "--force" in spawns[0]


def test_cursor_acp_launch_bypass_is_answered_by_the_relay() -> None:
    # ``cursor-agent acp`` accepts no flags; the relay answers every permission
    # request itself, so the launch route is unattended without one.
    assert CURSOR_ACP_BYPASS_IS_RELAY_ANSWERED is True


def test_an_unaccepted_bypass_disclaimer_is_named_with_its_recovery() -> None:
    stderr = (
        b"--bg with bypassPermissions requires accepting the disclaimer first."
    )

    assert classify_native_failure(stderr) == PERMISSION_BYPASS_UNACCEPTED

    fields = dict(
        native_diagnostic_fields({"native_error_class": PERMISSION_BYPASS_UNACCEPTED})
    )

    assert fields["Recovery"] == CLAUDE_BYPASS_DISCLAIMER_RECOVERY
