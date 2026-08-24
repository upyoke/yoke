"""Claude CLI stopped-session wake authorization tests."""

from __future__ import annotations

import pytest

from runtime.harness.test_session_relay_claude import (
    ACTUAL_ID,
    CHECK_INBOX,
    CLAUDE,
    _allow,
    _context,
)
from yoke_harness.session_relay_claude import (
    ClaudeProcessResult,
    run_claude_cli_adapter,
)


@pytest.mark.parametrize("scenario", ["claim-held", "chain-pending"])
def test_waiting_wake_resumes_active_labeled_session_at_private_version(
    scenario,
) -> None:
    invocations = []
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
        process_runner=lambda invocation: (
            invocations.append(invocation) or ClaudeProcessResult(0, 9)
        ),
        session_lookup=lookups.append,
        executable_finder=lambda _name: CLAUDE,
        version_gate=_allow,
    )

    assert invocations[0].argv == (
        CLAUDE,
        "-p",
        "--resume",
        ACTUAL_ID,
        CHECK_INBOX,
    )
    assert "--bg" not in invocations[0].argv
    assert result.result_code == "accepted"
    assert result.native_session_id is None
    assert lookups == []


def test_headless_resume_failure_is_failed_redacted_and_bounded() -> None:
    result = run_claude_cli_adapter(
        _context(
            job_kind="wake",
            native_instruction=CHECK_INBOX,
            target_session_id=ACTUAL_ID,
            launch_attestation=None,
            target_liveness="active",
            wake_mode="waiting",
        ),
        process_runner=lambda _invocation: ClaudeProcessResult(
            23,
            4_000_000,
            stdout="private message body",
            stderr="private bearer token",
        ),
        executable_finder=lambda _name: CLAUDE,
        version_gate=_allow,
    )

    assert result.result_code == "failed"
    assert result.evidence == {
        "result_code": "native_exit",
        "surface": "claude-cli",
        "duration_ms": 3_600_000,
        "exit_code": 23,
    }
    assert "private message body" not in repr(result)
    assert "private bearer token" not in repr(result)


@pytest.mark.parametrize("wake_mode", [None, "invented"])
def test_invalid_wake_mode_fails_before_native_discovery(wake_mode) -> None:
    result = run_claude_cli_adapter(
        _context(job_kind="wake", wake_mode=wake_mode, target_liveness="active")
    )

    assert result.result_code == "failed"
    assert result.evidence["result_code"] == "wake_mode_invalid"


def test_private_wake_version_mismatch_never_invokes_native_process() -> None:
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
        process_runner=calls.append,
        executable_finder=lambda _name: CLAUDE,
        version_gate=lambda *_args: False,
    )

    assert result.result_code == "version_mismatch"
    assert calls == []
