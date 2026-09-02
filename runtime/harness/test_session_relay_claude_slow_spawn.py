"""Slow and dead Claude native-create supervision tests."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
import json
import subprocess

import pytest

from yoke_contracts.session_control.launch_bootstrap import native_launch_bootstrap
from yoke_harness import session_relay_claude_process as process_module
from yoke_harness.session_relay_claude import run_claude_cli_adapter
from yoke_harness.session_relay_claude_process import run_bounded_claude_process
from yoke_harness.session_relay_runtime import RelayExecutionContext


LAUNCH_ID = "12345678-1234-4234-8234-123456789abc"
ACTUAL_ID = "87654321-4321-4321-8321-cba987654321"
SHORT_ID = "7c5dcf5d"


class _SlowProcess:
    pid = 4312

    def __init__(self) -> None:
        self.stdout = BytesIO(b"backgrounded output")
        self.stderr = BytesIO()
        self.returncode = None
        self.killed = False
        self.waits: list[float | None] = []

    def wait(self, timeout=None) -> int:
        self.waits.append(timeout)
        if len(self.waits) == 1:
            raise subprocess.TimeoutExpired(["claude"], timeout)
        self.returncode = 0
        return 0

    def poll(self):
        return self.returncode

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9


class _NeverFinishes(_SlowProcess):
    def wait(self, timeout=None) -> int:
        self.waits.append(timeout)
        if self.killed:
            return -9
        raise subprocess.TimeoutExpired(["claude"], timeout)


def test_live_process_continues_after_soft_bound(monkeypatch) -> None:
    process = _SlowProcess()
    popen_calls = []
    ticks = iter((10.0, 12.0, 12.0, 13.0))
    started = []
    exceeded = []
    monkeypatch.setattr(
        process_module.subprocess,
        "Popen",
        lambda argv, **kwargs: popen_calls.append((argv, kwargs)) or process,
    )
    monkeypatch.setattr(process_module.time, "monotonic", lambda: next(ticks))

    result = run_bounded_claude_process(
        ("claude", "--bg", "opaque"),
        cwd=Path("/project"),
        environment={"SAFE": "1"},
        timeout_seconds=2,
        continue_while_alive=True,
        hard_timeout_seconds=10,
        on_started=started.append,
        on_bound_exceeded=lambda pid, duration: exceeded.append((pid, duration)),
        start_new_session=True,
    )

    assert process.waits[0] == 2
    assert process.waits[1] == pytest.approx(8)
    assert process.killed is False
    assert started == [4312]
    assert exceeded == [(4312, 2_000)]
    assert result.pid == 4312
    assert result.bound_exceeded is True
    assert result.duration_ms == 3_000
    assert popen_calls[0][1]["start_new_session"] is True


def test_hard_bound_contains_a_process_that_never_finishes(monkeypatch) -> None:
    process = _NeverFinishes()
    ticks = iter((10.0, 12.0, 12.0))
    contained = []
    monkeypatch.setattr(
        process_module.subprocess,
        "Popen",
        lambda _argv, **_kwargs: process,
    )
    monkeypatch.setattr(process_module.time, "monotonic", lambda: next(ticks))

    with pytest.raises(subprocess.TimeoutExpired):
        run_bounded_claude_process(
            ("claude", "--bg", "opaque"),
            cwd=Path("/project"),
            environment={"SAFE": "1"},
            timeout_seconds=2,
            continue_while_alive=True,
            hard_timeout_seconds=4,
            on_hard_timeout=contained.append,
        )

    assert process.waits == [2, pytest.approx(2), None]
    assert contained == [4312]
    assert process.killed is True


def test_slow_live_spawn_hands_off_the_actual_session_identity() -> None:
    context = RelayExecutionContext(
        job_kind="launch",
        job_id=LAUNCH_ID,
        lease_id="lease-1",
        surface="claude-cli",
        surface_version="2.1.238",
        project_id=10,
        checkout=Path("/project"),
        native_instruction=native_launch_bootstrap(LAUNCH_ID),
        presentation="local",
        session_name="slow launch",
        launch_deadline_at="2099-01-01T00:00:00Z",
        launch_attestation="secret",
    )
    created = process_module.ClaudeProcessResult(
        0,
        38_000,
        f"backgrounded · {SHORT_ID} · Slow session\nclaude attach {SHORT_ID}",
        "",
        pid=4312,
        bound_exceeded=True,
    )
    identity = process_module.ClaudeProcessResult(
        0,
        12,
        json.dumps([{"id": SHORT_ID, "sessionId": ACTUAL_ID}]),
        "",
    )

    result = run_claude_cli_adapter(
        context,
        process_runner=lambda _invocation: created,
        session_lookup=lambda _invocation: identity,
        executable_finder=lambda _name: "/opt/claude/bin/claude",
        version_gate=lambda *_args: True,
        attestation_handoff=lambda *_args, **_kwargs: True,
    )

    assert result.result_code == "native_created"
    assert result.native_session_id == ACTUAL_ID
    assert result.evidence["native_launch_pid"] == 4312
    assert result.evidence["native_launch_phase"] == "spawn_completed_after_bound"
    assert result.evidence["duration_ms"] == 38_012


def test_dead_spawn_returns_a_private_typed_diagnostic() -> None:
    context = RelayExecutionContext(
        job_kind="launch",
        job_id=LAUNCH_ID,
        lease_id="lease-1",
        surface="claude-cli",
        surface_version="2.1.238",
        project_id=10,
        checkout=Path("/project"),
        native_instruction=native_launch_bootstrap(LAUNCH_ID),
        presentation="local",
        session_name="diagnostic launch",
        launch_deadline_at="2099-01-01T00:00:00Z",
        launch_attestation="secret",
    )

    def dead(_invocation):
        raise ProcessLookupError("native process exited before identity")

    result = run_claude_cli_adapter(
        context,
        process_runner=dead,
        executable_finder=lambda _name: "/opt/claude/bin/claude",
        version_gate=lambda *_args: True,
        attestation_handoff=lambda *_args, **_kwargs: True,
    )

    assert result.result_code == "outcome_unknown"
    assert result.evidence["result_code"] == "native_exception"
    assert result.private_diagnostic is not None
    assert result.private_diagnostic.failure_class == "native_exception"
    assert result.private_diagnostic.error_step == "launch"
    assert "native process exited" not in repr(result.evidence)
