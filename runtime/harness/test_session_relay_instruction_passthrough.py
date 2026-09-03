"""The native reads the control plane's own sentence, not the relay's copy.

An adapter that rebuilt the instruction and demanded equality tied relay and
control plane into a build lockstep neither of them declares. The wording
changed on one side of a deploy window, every native wake on the machine
refused as `instruction_invalid`, and four steering waits died against a
relay that never spawned anything for two hours. So the adapter no longer
owns the wording; it checks that the sentence names this job's own target
and hands those bytes through.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from yoke_contracts.session_control.launch_bootstrap import native_launch_bootstrap
from yoke_contracts.session_control.wake_instruction import native_wake_instruction
from yoke_harness.session_relay_claude import run_claude_cli_adapter
from yoke_harness.session_relay_runtime import native_instruction_targets_job


LAUNCH_ID = "12345678-1234-4234-8234-123456789abc"
MESSAGE_ID = "message-1"
TARGET_SESSION = "87654321-4321-4321-8321-cba987654321"


def _wake_context(**overrides):
    values = {
        "job_kind": "wake",
        "job_id": "job-1",
        "lease_id": "lease-1",
        "surface": "claude-cli",
        "surface_version": "2.1.238",
        "project_id": 10,
        "checkout": Path("/project"),
        "native_instruction": native_wake_instruction(MESSAGE_ID),
        "message_id": MESSAGE_ID,
        "target_session_id": TARGET_SESSION,
        "launch_attestation": None,
        "requested_model": None,
        "presentation": "local",
        "session_name": None,
        "launch_deadline_at": None,
        "launch_progress_reporter": None,
        "target_liveness": "ended",
        "wake_mode": "waiting",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_a_sentence_naming_this_job_passes_whatever_its_wording() -> None:
    """The peer that authored it may be a different build than this one."""
    older_wording = (
        f"Yoke message {MESSAGE_ID} is pending for this session. "
        "Run `yoke sessions touch` first."
    )

    assert native_instruction_targets_job(_wake_context())
    assert native_instruction_targets_job(
        _wake_context(native_instruction=older_wording)
    )


@pytest.mark.parametrize(
    "context",
    [
        _wake_context(native_instruction=native_wake_instruction("another-message")),
        _wake_context(native_instruction=""),
        _wake_context(message_id=None),
    ],
    ids=["another-message", "empty", "no-target"],
)
def test_a_sentence_aimed_elsewhere_is_refused(context) -> None:
    assert not native_instruction_targets_job(context)


def test_a_launch_sentence_must_name_its_own_launch() -> None:
    launch = SimpleNamespace(
        job_kind="launch",
        job_id=LAUNCH_ID,
        message_id=None,
        native_instruction=native_launch_bootstrap(LAUNCH_ID),
    )

    assert native_instruction_targets_job(launch)
    assert not native_instruction_targets_job(
        SimpleNamespace(
            job_kind="launch",
            job_id=LAUNCH_ID,
            message_id=None,
            native_instruction=native_launch_bootstrap("some-other-launch"),
        )
    )


def test_the_native_is_handed_the_control_planes_bytes(monkeypatch) -> None:
    """Not a re-derivation that happened to compare equal.

    The relay validating one string and delivering another is how a wake
    prompt drifts out of step with the acknowledgement the receipt waits for.
    """
    control_plane_wording = (
        f"Yoke message {MESSAGE_ID} is pending; run `yoke messages get "
        f"{MESSAGE_ID} --json` first."
    )
    spawned: list[str] = []

    monkeypatch.setattr(
        "yoke_harness.session_relay_claude.claude_session_transcript_exists",
        lambda *_args, **_kwargs: True,
    )
    result = run_claude_cli_adapter(
        _wake_context(native_instruction=control_plane_wording),
        executable_finder=lambda _name: "/opt/claude/bin/claude",
        version_gate=lambda *_args: True,
        wake_spawner=lambda _context, invocation: (
            spawned.append(invocation.instruction)
            or SimpleNamespace(evidence={"result_code": "accepted"})
        ),
    )

    assert result.result_code
    assert spawned == [control_plane_wording]
