"""Detached Claude resume process ownership and capture tests."""

from __future__ import annotations

from pathlib import Path
import signal

from yoke_contracts.session_control.resume import RESUME_ATTEMPT_ENV
from yoke_harness import session_relay_claude_native as native_module
from yoke_harness import session_relay_claude_resume as resume_module
from yoke_harness.session_relay_claude_native import (
    ClaudeNativeInvocation,
    spawn_claude_wake,
)
from yoke_harness.session_relay_claude_process import ClaudeProcessResult
from yoke_harness.session_relay_claude_resume import (
    spawn_detached_claude_resume,
)
from yoke_harness.session_relay_runtime import RelayExecutionContext


ATTEMPT_ID = "11111111-1111-4111-8111-111111111111"
SESSION_ID = "22222222-2222-4222-8222-222222222222"


class _Process:
    pid = 4321

    def __init__(self) -> None:
        self.terminated = False
        self.killed = False

    def terminate(self) -> None:
        self.terminated = True

    def wait(self, timeout=None) -> int:
        del timeout
        return 0

    def kill(self) -> None:
        self.killed = True


def test_resume_spawn_detaches_redirects_and_records_custody(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls = []
    custody = []
    process = _Process()

    def factory(argv, **kwargs):
        calls.append((argv, kwargs))
        return process

    monkeypatch.setattr(
        resume_module,
        "record_supervised_native",
        lambda *args, **kwargs: custody.append((args, kwargs)) or True,
    )
    result = spawn_detached_claude_resume(
        ["/opt/claude", "-p", "--resume", SESSION_ID],
        checkout=tmp_path,
        environment={"SAFE": "1"},
        attempt_id=ATTEMPT_ID,
        native_session_id=SESSION_ID,
        binary_source="path",
        state_dir=tmp_path,
        process_factory=factory,
        clock=lambda: 1_777_000_000.0,
    )

    assert result is not None and result.pid == process.pid
    argv, kwargs = calls[0]
    assert argv[:2] == ["/opt/claude", "-p"]
    assert kwargs["cwd"] == tmp_path
    assert kwargs["env"] == {"SAFE": "1"}
    assert kwargs["stdin"] is not None
    assert kwargs["start_new_session"] is True
    assert kwargs["stderr"] == -2
    assert kwargs["stdout"].closed
    assert result.capture_path.exists()
    assert result.capture_path.stat().st_mode & 0o777 == 0o600
    assert custody[0][0] == (ATTEMPT_ID, process.pid)
    assert custody[0][1]["supervision_kind"] == "resume"
    assert custody[0][1]["capture_path"] == result.capture_path


def test_resume_spawn_stops_native_when_custody_record_cannot_be_written(
    tmp_path: Path,
    monkeypatch,
) -> None:
    process = _Process()
    group_signals = []
    monkeypatch.setattr(
        resume_module,
        "record_supervised_native",
        lambda *args, **kwargs: False,
    )
    monkeypatch.setattr(
        resume_module.os,
        "killpg",
        lambda pid, sent: group_signals.append((pid, sent)),
    )

    result = spawn_detached_claude_resume(
        ["/opt/claude"],
        checkout=tmp_path,
        environment={},
        attempt_id=ATTEMPT_ID,
        native_session_id=SESSION_ID,
        binary_source="path",
        state_dir=tmp_path,
        process_factory=lambda *args, **kwargs: process,
    )

    assert result is None
    assert group_signals == [(process.pid, signal.SIGTERM)]
    assert not process.terminated
    assert not tuple((tmp_path / "claude-resume-captures").glob("*.capture"))


def test_resume_spawn_refuses_an_untrusted_attempt_filename(tmp_path: Path) -> None:
    calls = []
    result = spawn_detached_claude_resume(
        ["/opt/claude"],
        checkout=tmp_path,
        environment={},
        attempt_id="../../escape",
        native_session_id=SESSION_ID,
        binary_source="path",
        state_dir=tmp_path,
        process_factory=lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    assert result is None
    assert calls == []


def test_native_wake_environment_carries_only_its_resume_attempt(
    tmp_path: Path,
    monkeypatch,
) -> None:
    captured = {}
    monkeypatch.setenv("YOKE_SESSION_ID", "parent-session")
    monkeypatch.setattr(
        native_module,
        "spawn_detached_claude_resume",
        lambda *args, **kwargs: captured.update(kwargs),
    )
    context = RelayExecutionContext(
        job_kind="wake",
        job_id=ATTEMPT_ID,
        lease_id="lease",
        surface="claude-cli",
        project_id=1,
        checkout=tmp_path,
        native_instruction="message ref",
        surface_version="2.1.238",
        target_session_id=SESSION_ID,
    )
    invocation = ClaudeNativeInvocation(
        "/opt/claude",
        tmp_path,
        SESSION_ID,
        "2.1.238",
        "message ref",
        resume=True,
    )

    spawn_claude_wake(
        context,
        invocation,
        session_lookup=lambda _invocation: ClaudeProcessResult(0, 1, "[]"),
    )

    assert captured["attempt_id"] == ATTEMPT_ID
    assert captured["environment"][RESUME_ATTEMPT_ENV] == ATTEMPT_ID
    assert "YOKE_SESSION_ID" not in captured["environment"]
    assert captured["environment"]["SHELL"] == "/bin/sh"
