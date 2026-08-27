"""Claude CLI stopped-session detached-wake authorization tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.harness.test_session_relay_claude import (
    ACTUAL_ID,
    CHECK_INBOX,
    CLAUDE,
    _allow,
    _context,
)
from yoke_contracts.session_control.resume import RESUMED_RUNNING_RESULT
from yoke_harness import session_relay_claude as claude_module
from yoke_harness.session_relay_claude import run_claude_cli_adapter
from yoke_harness.session_relay_claude_resume import ClaudeResumeProcess


WAKE_PROMPT = (
    "Yoke message reference `message-1` is pending. Inspect and handle authenticated "
    "Yoke messages through normal Yoke hooks or message surfaces."
)


@pytest.fixture(autouse=True)
def _transcript_present_by_default(monkeypatch):
    monkeypatch.setattr(
        claude_module,
        "claude_session_transcript_exists",
        lambda checkout, session_id: True,
    )


def _spawned(calls):
    def spawn(context, invocation):
        calls.append((context, invocation))
        return ClaudeResumeProcess(
            4321,
            invocation.executable,
            "path",
            Path("/private/captures/resume.capture"),
            "2026-08-25T12:00:00Z",
        )

    return spawn


@pytest.mark.parametrize("scenario", ["claim-held", "chain-pending"])
def test_waiting_wake_spawns_exact_yoke_session_and_returns_running(
    scenario,
) -> None:
    spawns = []
    lookups = []
    result = run_claude_cli_adapter(
        _context(
            job_kind="wake",
            job_id=scenario,
            native_instruction=CHECK_INBOX,
            target_session_id=ACTUAL_ID,
            launch_attestation=None,
            target_liveness="active",
            wake_mode="waiting",
        ),
        wake_spawner=_spawned(spawns),
        session_lookup=lookups.append,
        executable_finder=lambda _name: CLAUDE,
        version_gate=_allow,
    )

    context, invocation = spawns[0]
    assert invocation.argv == (
        CLAUDE,
        "-p",
        "--resume",
        ACTUAL_ID,
        WAKE_PROMPT,
        "--output-format",
        "json",
    )
    assert invocation.session_id == ACTUAL_ID
    assert invocation.instruction == WAKE_PROMPT
    assert context.job_id == scenario
    assert all(
        token not in invocation.argv
        for token in ("--bg", "--name", "ListAgents", "SendMessage")
    )
    assert result.result_code == RESUMED_RUNNING_RESULT
    assert result.native_session_id is None
    assert result.evidence == {
        "result_code": RESUMED_RUNNING_RESULT,
        "native_pid": 4321,
        "native_binary": CLAUDE,
        "native_binary_source": "path",
        "native_capture_path": "/private/captures/resume.capture",
        "native_started_at": "2026-08-25T12:00:00Z",
        "surface": "claude-cli",
    }
    assert lookups == []


def test_detached_resume_spawn_failure_is_terminal_for_the_relay_cycle() -> None:
    result = run_claude_cli_adapter(
        _context(
            job_kind="wake",
            native_instruction=CHECK_INBOX,
            target_session_id=ACTUAL_ID,
            target_liveness="active",
            wake_mode="waiting",
        ),
        wake_spawner=lambda _context, _invocation: None,
        executable_finder=lambda _name: CLAUDE,
        version_gate=_allow,
    )

    assert result.result_code == "failed"
    assert result.evidence["result_code"] == "resume_spawn_failed"


def test_detached_resume_native_exception_stays_private() -> None:
    def explode(_context, _invocation):
        raise OSError("private bearer token")

    result = run_claude_cli_adapter(
        _context(
            job_kind="wake",
            native_instruction=CHECK_INBOX,
            target_session_id=ACTUAL_ID,
            target_liveness="active",
            wake_mode="waiting",
        ),
        wake_spawner=explode,
        executable_finder=lambda _name: CLAUDE,
        version_gate=_allow,
    )

    assert result.result_code == "failed"
    assert result.evidence["result_code"] == "native_exception"
    assert "private bearer token" not in repr(result)
    assert result.private_diagnostic is not None


@pytest.mark.parametrize("wake_mode", [None, "invented"])
def test_invalid_wake_mode_fails_before_native_discovery(wake_mode) -> None:
    result = run_claude_cli_adapter(
        _context(job_kind="wake", wake_mode=wake_mode, target_liveness="active")
    )

    assert result.result_code == "failed"
    assert result.evidence["result_code"] == "wake_mode_invalid"


def test_private_wake_version_mismatch_never_spawns_native_process() -> None:
    calls = []
    result = run_claude_cli_adapter(
        _context(
            job_kind="wake",
            native_instruction=CHECK_INBOX,
            target_session_id=ACTUAL_ID,
            surface_version="2.1.239",
            target_liveness="active",
            wake_mode="waiting",
        ),
        wake_spawner=lambda *args: calls.append(args),
        executable_finder=lambda _name: CLAUDE,
        version_gate=lambda *_args: False,
    )

    assert result.result_code == "version_mismatch"
    assert calls == []


def test_stopped_wake_refuses_when_transcript_missing(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        claude_module,
        "claude_session_transcript_exists",
        lambda checkout, session_id: False,
    )
    result = run_claude_cli_adapter(
        _context(
            job_kind="wake",
            native_instruction=CHECK_INBOX,
            target_session_id=ACTUAL_ID,
            target_liveness="ended",
            wake_mode="waiting",
        ),
        wake_spawner=lambda *args: calls.append(args),
        executable_finder=lambda _name: CLAUDE,
        version_gate=_allow,
    )

    assert result.result_code == "failed"
    assert result.evidence["result_code"] == "transcript_missing"
    assert calls == []


def test_stopped_wake_spawns_when_transcript_exists() -> None:
    calls = []
    result = run_claude_cli_adapter(
        _context(
            job_kind="wake",
            native_instruction=CHECK_INBOX,
            target_session_id=ACTUAL_ID,
            target_liveness="ended",
            wake_mode="waiting",
        ),
        wake_spawner=_spawned(calls),
        executable_finder=lambda _name: CLAUDE,
        version_gate=_allow,
    )

    assert result.result_code == RESUMED_RUNNING_RESULT
    assert len(calls) == 1
    assert calls[0][1].resume is True
