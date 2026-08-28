"""A Claude wake must deliver and be acknowledged on its first attempt."""

from __future__ import annotations

from functools import partial
import json
from pathlib import Path

import pytest

from runtime.harness.test_session_relay_claude import (
    ACTUAL_ID,
    CHECK_INBOX,
    CLAUDE,
    SHORT_ID,
    _agents,
    _allow,
    _context,
    _created,
)
from yoke_contracts.session_control.resume import RESUMED_RUNNING_RESULT
from yoke_contracts.session_control.presentation import (
    CLAUDE_REMOTE_CONTROL_SETTING,
)
from yoke_contracts.session_control.wake_instruction import native_wake_instruction
from yoke_harness import session_relay_claude as claude_module
from yoke_harness import session_relay_claude_native as native_module
from yoke_harness.session_relay_claude import run_claude_cli_adapter
from yoke_harness.session_relay_claude_native import spawn_claude_wake
from yoke_harness.session_relay_claude_process import ClaudeProcessResult
from yoke_harness.session_relay_claude_resume import ClaudeResumeProcess


@pytest.fixture(autouse=True)
def _transcript_present(monkeypatch):
    monkeypatch.setattr(
        claude_module,
        "claude_session_transcript_exists",
        lambda checkout, session_id: True,
    )


def _background_wake(monkeypatch, *, stop_returncode: int = 0):
    """Wake a background-launched session and capture what the relay ran."""
    launch = run_claude_cli_adapter(
        _context(),
        process_runner=lambda _invocation: _created(),
        session_lookup=lambda _invocation: _agents(),
        executable_finder=lambda _name: CLAUDE,
        version_gate=_allow,
        attestation_handoff=lambda *_args, **_kwargs: True,
    )
    assert launch.native_session_id == ACTUAL_ID
    commands: list[tuple[str, ...]] = []
    detached: list[tuple[tuple[str, ...], dict]] = []

    def run_command(_invocation, argv):
        commands.append(argv)
        return ClaudeProcessResult(stop_returncode, 3, "", "")

    def spawn(argv, **kwargs):
        detached.append((argv, kwargs))
        return ClaudeResumeProcess(
            4321,
            CLAUDE,
            "path",
            Path("/private/captures/background-resume.capture"),
            "2026-08-26T12:00:00Z",
            kwargs.get("background_job") or {},
        )

    monkeypatch.setattr(native_module, "_run_claude_command", run_command)
    monkeypatch.setattr(native_module, "spawn_detached_claude_resume", spawn)
    wake = run_claude_cli_adapter(
        _context(
            job_kind="wake",
            job_id="11111111-1111-4111-8111-111111111111",
            native_instruction=CHECK_INBOX,
            target_session_id=launch.native_session_id,
            launch_attestation=None,
            target_liveness="ended",
            wake_mode="waiting",
        ),
        wake_spawner=partial(
            spawn_claude_wake,
            session_lookup=lambda _invocation: _agents(),
        ),
        executable_finder=lambda _name: CLAUDE,
        version_gate=_allow,
    )
    return wake, commands, detached


def test_background_session_wake_stops_the_job_and_carries_the_prompt(
    monkeypatch,
) -> None:
    """A resumed turn only delivers when it carries the wake prompt.

    The promptless restart verb reactivated the session and ended the turn
    without a single hook, so the pending envelope was never injected.
    """
    wake, commands, detached = _background_wake(monkeypatch)

    assert commands == [(CLAUDE, "stop", SHORT_ID)]
    argv, kwargs = detached[0]
    assert argv == (
        CLAUDE,
        "-p",
        "--dangerously-skip-permissions",
        "--settings",
        json.dumps(
            {CLAUDE_REMOTE_CONTROL_SETTING: True},
            separators=(",", ":"),
        ),
        "--resume",
        ACTUAL_ID,
        CHECK_INBOX,
        "--output-format",
        "json",
    )
    assert kwargs["native_session_id"] == ACTUAL_ID
    assert wake.result_code == RESUMED_RUNNING_RESULT
    assert wake.evidence["background_agent_result"] == "background_agent_resolved"
    assert wake.evidence["background_agent_stop"] == "completed"


def test_background_job_stop_failure_still_resumes_and_names_itself(
    monkeypatch,
) -> None:
    wake, _commands, detached = _background_wake(monkeypatch, stop_returncode=1)

    assert detached[0][0][1] == "-p"
    assert wake.evidence["background_agent_stop"] == "native_exit"


def test_wake_without_a_background_job_skips_the_stop(monkeypatch) -> None:
    detached: list[tuple[tuple[str, ...], dict]] = []
    commands: list[tuple[str, ...]] = []

    def spawn(argv, **kwargs):
        detached.append((argv, kwargs))
        return ClaudeResumeProcess(
            4321,
            CLAUDE,
            "path",
            Path("/private/captures/plain-resume.capture"),
            "2026-08-26T12:00:00Z",
            kwargs.get("background_job") or {},
        )

    monkeypatch.setattr(
        native_module,
        "_run_claude_command",
        lambda _invocation, argv: commands.append(argv),
    )
    monkeypatch.setattr(native_module, "spawn_detached_claude_resume", spawn)
    wake = run_claude_cli_adapter(
        _context(
            job_kind="wake",
            job_id="11111111-1111-4111-8111-111111111111",
            native_instruction=CHECK_INBOX,
            target_session_id=ACTUAL_ID,
            launch_attestation=None,
            target_liveness="ended",
            wake_mode="waiting",
        ),
        wake_spawner=partial(
            spawn_claude_wake,
            session_lookup=lambda _invocation: _agents(rows=[]),
        ),
        executable_finder=lambda _name: CLAUDE,
        version_gate=_allow,
    )

    assert commands == []
    assert detached[0][0][:7] == (
        CLAUDE,
        "-p",
        "--dangerously-skip-permissions",
        "--settings",
        json.dumps(
            {CLAUDE_REMOTE_CONTROL_SETTING: True},
            separators=(",", ":"),
        ),
        "--resume",
        ACTUAL_ID,
    )
    assert wake.evidence["background_agent_result"] == "background_agent_not_found"


def test_wake_prompt_asks_the_resumed_turn_for_the_acknowledgement() -> None:
    """The prompt names the action, not just the message.

    A resumed turn whose transcript is a conversation rather than a worker
    mandate will answer an announcement in prose and end, leaving the plane
    to wake it again for a receipt the first wake had already earned. The
    prompt therefore asks for the acknowledgement inside this turn — and
    withholds it when no envelope arrived, so a wake that failed to deliver
    cannot be acknowledged into looking successful.
    """
    message_id = "11111111-1111-4111-8111-111111111111"
    prompt = native_wake_instruction(message_id)

    assert message_id in prompt
    assert "acknowledge" in prompt
    assert "this turn" in prompt
    assert "If no envelope was injected, do not acknowledge" in prompt
