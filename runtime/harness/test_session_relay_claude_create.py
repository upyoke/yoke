"""Relay-owned Claude create: custody, identity, and immediate refusal."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from yoke_harness.session_launch_containment import supervised_records
from yoke_harness.session_launch_handoff import LAUNCH_CONTEXT_ENV
from yoke_harness.session_relay_native_create import immediate_native_refusal
from yoke_harness.session_relay_claude_native import (
    ClaudeNativeInvocation,
    spawn_claude_create,
    spawn_claude_wake,
)
from yoke_harness.session_relay_native_capture_format import (
    STATE_RUNNING,
    compose_capture,
)
from yoke_harness.session_relay_native_spawn import spawn_supervised_native


LAUNCH_ID = "12345678-1234-4234-8234-123456789abc"
NATIVE_ID = "87654321-4321-4321-8321-cba987654321"
CLAUDE = "/opt/claude/bin/claude"


class _Process:
    # This process's own pid, so custody records a start time that really
    # resolves; a pid nothing owns fails custody and is reaped instead.
    pid = os.getpid()

    def terminate(self) -> None:
        return None

    def wait(self, timeout=None) -> int:
        del timeout
        return 0

    def kill(self) -> None:
        return None


def test_a_launch_is_supervised_as_a_launch_not_a_resume(tmp_path: Path) -> None:
    """A launch and a resume are settled by different readers of one record.

    Resume settlement claims every record it finds marked ``resume``; a launch
    filed under that kind would be reported as a finished wake attempt against
    a lease no wake ever took.
    """
    started = spawn_supervised_native(
        [CLAUDE, "-p", "hello"],
        checkout=tmp_path,
        environment={},
        attempt_id=LAUNCH_ID,
        native_session_id=NATIVE_ID,
        binary_source="path",
        supervision_kind="launch",
        state_dir=tmp_path,
        process_factory=lambda *_args, **_kwargs: _Process(),
    )

    assert started is not None
    records = [payload for _path, payload in supervised_records(tmp_path)]
    assert len(records) == 1
    assert records[0]["supervision_kind"] == "launch"
    assert records[0]["launch_id"] == LAUNCH_ID
    assert records[0]["native_session_id"] == NATIVE_ID
    assert records[0]["capture_path"] == str(started.capture_path)


def test_a_resume_remains_the_default_supervision_kind(tmp_path: Path) -> None:
    started = spawn_supervised_native(
        [CLAUDE, "-p", "--resume", NATIVE_ID],
        checkout=tmp_path,
        environment={},
        attempt_id=LAUNCH_ID,
        native_session_id=NATIVE_ID,
        binary_source="path",
        state_dir=tmp_path,
        process_factory=lambda *_args, **_kwargs: _Process(),
    )

    assert started is not None
    records = [payload for _path, payload in supervised_records(tmp_path)]
    assert records[0]["supervision_kind"] == "resume"


@pytest.mark.parametrize("exit_code", [0, 2, None])
def test_a_native_that_already_ended_is_read_back_from_its_capture(
    tmp_path: Path,
    exit_code: int | None,
) -> None:
    capture = tmp_path / "ended.capture"
    capture.write_bytes(
        compose_capture(stdout=b"", stderr=b"refused", exit_code=exit_code)
    )

    refusal = immediate_native_refusal(capture, window_seconds=0.0)

    assert refusal is not None
    assert refusal.exit_code == exit_code
    assert refusal.stderr == b"refused"


def test_a_native_still_running_is_left_to_registration(tmp_path: Path) -> None:
    capture = tmp_path / "running.capture"
    capture.write_bytes(compose_capture(stdout=b"", stderr=b"", state=STATE_RUNNING))
    slept: list[float] = []

    assert (
        immediate_native_refusal(
            capture,
            window_seconds=1.0,
            monotonic=lambda: 0.0 if not slept else 99.0,
            sleeper=slept.append,
        )
        is None
    )
    assert slept


def test_a_capture_that_never_appeared_is_not_a_refusal(tmp_path: Path) -> None:
    assert (
        immediate_native_refusal(tmp_path / "absent.capture", window_seconds=0.0)
        is None
    )


def test_create_environment_carries_the_launch_context_not_the_parent(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("CODEX_SESSION_ID", "parent-session")
    calls: list[dict] = []
    monkeypatch.setattr(
        "yoke_harness.session_relay_claude_native.spawn_supervised_native",
        lambda argv, **kwargs: calls.append({"argv": argv, **kwargs}) or None,
    )
    invocation = ClaudeNativeInvocation(
        CLAUDE,
        tmp_path,
        NATIVE_ID,
        "2.1.238",
        "instruction",
        launch_id=LAUNCH_ID,
        launch_attestation="secret-attestation",
    )

    assert spawn_claude_create(invocation) is None
    environment = calls[0]["environment"]
    assert "CODEX_SESSION_ID" not in environment
    assert json.loads(environment[LAUNCH_CONTEXT_ENV]) == {
        "launch_id": LAUNCH_ID,
        "attestation": "secret-attestation",
    }
    assert calls[0]["attempt_id"] == LAUNCH_ID
    assert calls[0]["native_session_id"] == NATIVE_ID
    assert calls[0]["supervision_kind"] == "launch"


def test_wake_environment_carries_no_launch_context(
    tmp_path: Path, monkeypatch
) -> None:
    calls: list[dict] = []
    monkeypatch.setattr(
        "yoke_harness.session_relay_claude_native.spawn_supervised_native",
        lambda argv, **kwargs: calls.append({"argv": argv, **kwargs}) or None,
    )
    context = type("Context", (), {"job_id": LAUNCH_ID, "lease_id": "lease-1"})()
    invocation = ClaudeNativeInvocation(
        CLAUDE,
        tmp_path,
        NATIVE_ID,
        "2.1.238",
        "wake up",
        resume=True,
    )

    assert spawn_claude_wake(context, invocation) is None
    assert LAUNCH_CONTEXT_ENV not in calls[0]["environment"]
    assert calls[0]["native_session_id"] == NATIVE_ID
    assert "supervision_kind" not in calls[0]
