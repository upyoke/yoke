"""A Claude wake must deliver and be acknowledged on its first attempt."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime.harness.test_session_relay_claude import (
    CHECK_INBOX,
    CLAUDE,
    _allow,
    _context,
)
from yoke_contracts.session_control.resume import RESUMED_RUNNING_RESULT
from yoke_contracts.session_control.presentation import (
    CLAUDE_REMOTE_CONTROL_SETTING,
)
from yoke_contracts.session_control.wake_instruction import native_wake_instruction
from yoke_harness import session_relay_claude as claude_module
from yoke_harness import session_relay_claude_native as native_module
from yoke_harness.session_relay_claude import run_claude_cli_adapter
from yoke_harness.session_relay_native_spawn import SupervisedNative


TARGET_ID = "87654321-4321-4321-8321-cba987654321"
LOCAL_SETTINGS = json.dumps(
    {CLAUDE_REMOTE_CONTROL_SETTING: True},
    separators=(",", ":"),
)


@pytest.fixture(autouse=True)
def _transcript_present(monkeypatch):
    monkeypatch.setattr(
        claude_module,
        "claude_session_transcript_exists",
        lambda checkout, session_id: True,
    )


def _wake(monkeypatch):
    """Wake a stopped session and capture exactly what the relay ran."""
    detached: list[tuple[tuple[str, ...], dict]] = []

    def spawn(argv, **kwargs):
        detached.append((argv, kwargs))
        return SupervisedNative(
            4321,
            CLAUDE,
            "path",
            Path("/private/captures/resume.capture"),
            "nd-44444444-4444-4444-8444-444444444444",
            "2026-08-26T12:00:00Z",
        )

    monkeypatch.setattr(native_module, "spawn_supervised_native", spawn)
    wake = run_claude_cli_adapter(
        _context(
            job_kind="wake",
            job_id="11111111-1111-4111-8111-111111111111",
            native_instruction=CHECK_INBOX,
            target_session_id=TARGET_ID,
            launch_attestation=None,
            target_liveness="ended",
            wake_mode="waiting",
        ),
        executable_finder=lambda _name: CLAUDE,
        version_gate=_allow,
    )
    return wake, detached


def test_wake_resumes_the_conversation_and_carries_the_prompt(monkeypatch) -> None:
    """A resumed turn only delivers when it carries the wake prompt.

    The promptless restart verb reactivated the session and ended the turn
    without a single hook, so the pending envelope was never injected.
    """
    wake, detached = _wake(monkeypatch)

    argv, kwargs = detached[0]
    assert argv == (
        CLAUDE,
        "-p",
        "--dangerously-skip-permissions",
        "--settings",
        LOCAL_SETTINGS,
        "--resume",
        TARGET_ID,
        CHECK_INBOX,
        "--output-format",
        "json",
    )
    assert kwargs["native_session_id"] == TARGET_ID
    assert wake.result_code == RESUMED_RUNNING_RESULT
    assert wake.evidence["native_pid"] == 4321


def test_wake_asks_no_second_owner_to_release_the_conversation(monkeypatch) -> None:
    """The previous turn's process is gone, so nothing holds the transcript.

    While a daemon job owned the conversation, a headless resume of a session
    it still held was refused outright, and a parked worker could only be
    woken by terminating and relaunching it.
    """
    wake, detached = _wake(monkeypatch)

    assert len(detached) == 1
    assert not [key for key in wake.evidence if key.startswith("background_")]


def test_wake_prompt_asks_the_resumed_turn_for_the_acknowledgement() -> None:
    """The prompt names the action, not just the message.

    A resumed turn whose transcript is a conversation rather than a worker
    mandate will answer an announcement in prose and end, leaving the plane
    to wake it again for a receipt the first wake had already earned. The
    prompt therefore names the read that returns the message body, asks for
    the acknowledgement inside this turn, and withholds it when the read
    found nothing — so a wake that failed to deliver cannot be acknowledged
    into looking successful.
    """
    message_id = "11111111-1111-4111-8111-111111111111"
    prompt = native_wake_instruction(message_id)

    assert message_id in prompt
    assert f"yoke messages get {message_id} --json" in prompt
    assert f"yoke messages acknowledge {message_id}" in prompt
    assert "this turn" in prompt
    assert "If the read reported no such message, do not acknowledge" in prompt
