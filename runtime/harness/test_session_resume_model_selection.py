"""Native resume selection and identity contracts for supported CLIs."""

from __future__ import annotations

from pathlib import Path

from yoke_contracts.session_control.model_selection_manifest import (
    launch_model_selection_manifest,
)
from yoke_contracts.session_control.wake_instruction import native_wake_instruction
from yoke_harness.session_relay_claude_native import native_invocation
from yoke_harness.session_relay_codex import (
    CodexNativeOutcome,
    build_codex_relay_adapter,
)
from yoke_harness.session_relay_codex_invocation import codex_base_command
from yoke_harness.session_relay_cursor import (
    CursorNativeResult,
    build_cursor_adapter,
)
from yoke_harness.session_relay_runtime import RelayExecutionContext


MESSAGE_ID = "11111111-1111-4111-8111-111111111111"
SESSION_ID = "22222222-2222-4222-8222-222222222222"
THREAD_ID = "33333333-3333-4333-8333-333333333333"


def _context(
    surface: str, *, context_window_tokens: int | None = 1_000_000
) -> RelayExecutionContext:
    return RelayExecutionContext(
        job_kind="wake",
        job_id="attempt-1",
        lease_id="lease-1",
        surface=surface,
        surface_version="current",
        project_id=1,
        checkout=Path("/project"),
        native_instruction=native_wake_instruction(MESSAGE_ID),
        message_id=MESSAGE_ID,
        target_session_id=SESSION_ID,
        target_native_thread_id=THREAD_ID,
        requested_model="gpt-5.6-sol",
        requested_reasoning_effort="xhigh",
        requested_context_window_tokens=context_window_tokens,
        wake_mode="waiting",
        target_liveness="ended",
    )


def test_resume_manifest_names_native_and_explicit_contracts() -> None:
    assert launch_model_selection_manifest("claude-cli")["resume_selection"] == (
        "native"
    )
    assert launch_model_selection_manifest("codex-cli")["resume_selection"] == (
        "explicit"
    )
    assert launch_model_selection_manifest("cursor-cli")["resume_selection"] == (
        "native"
    )


def test_claude_resume_keeps_identity_and_omits_selection_override() -> None:
    invocation = native_invocation(
        _context("claude-cli"),
        "/opt/claude",
        native_wake_instruction(MESSAGE_ID),
    )

    assert invocation is not None
    assert invocation.session_id == SESSION_ID
    assert invocation.resume is True
    assert ("--resume", SESSION_ID) in tuple(zip(invocation.argv, invocation.argv[1:]))
    assert "--model" not in invocation.argv
    assert "--effort" not in invocation.argv


class _CodexPort:
    request = None

    def create(self, request):
        raise AssertionError("wake test must not create")

    def wake(self, request):
        self.request = request
        return CodexNativeOutcome("accepted", identity_correlated=True)


def test_codex_resume_replays_current_selection_on_exact_thread() -> None:
    port = _CodexPort()
    adapter = build_codex_relay_adapter(
        cli_transport=port,
        desktop_transport=port,
        version_gate=lambda _surface, _version, _operation: True,
    )

    result = adapter(_context("codex-cli", context_window_tokens=None))

    assert result.result_code == "accepted"
    assert port.request is not None
    assert port.request.target_session_id == SESSION_ID
    assert port.request.target_thread_id == THREAD_ID
    command = codex_base_command("/opt/codex", port.request)
    assert ("--model", "gpt-5.6-sol") in tuple(zip(command, command[1:]))
    assert ("-c", "model_reasoning_effort=xhigh") in tuple(zip(command, command[1:]))
    assert "--ignore-user-config" not in command


class _CursorPort:
    request = None

    def new_session(self, request):
        raise AssertionError("wake test must not create")

    def resume_chat(self, request):
        self.request = request
        return CursorNativeResult("accepted")


def test_cursor_resume_keeps_identity_and_omits_selection_override() -> None:
    port = _CursorPort()
    adapter = build_cursor_adapter(
        subprocess_port=port,
        version_gate=lambda _surface, _version, _operation: True,
    )

    result = adapter(_context("cursor-cli"))

    assert result.result_code == "accepted"
    assert port.request is not None
    assert port.request.target_session_id == SESSION_ID
    assert port.request.requested_model is None
