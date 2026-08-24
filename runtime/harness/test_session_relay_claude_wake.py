"""Claude CLI stopped-session wake authorization tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime.harness.test_session_relay_claude import (
    ACTUAL_ID,
    CHECK_INBOX,
    CLAUDE,
    _allow,
    _context,
)
from yoke_harness import session_relay_claude as claude_module
from yoke_harness.session_relay_claude import (
    CLAUDE_HEADLESS_WAKE_TIMEOUT_SECONDS,
    CLAUDE_NATIVE_TIMEOUT_SECONDS,
    ClaudeNativeInvocation,
    ClaudeProcessResult,
    run_claude_cli_adapter,
    run_claude_process,
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
            invocations.append(invocation)
            or ClaudeProcessResult(
                0,
                9,
                stdout=json.dumps(
                    {
                        "session_id": ACTUAL_ID.upper(),
                        "result": "private response body",
                    }
                ),
                stderr="private bearer token",
            )
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
        "--output-format",
        "json",
    )
    assert "--bg" not in invocations[0].argv
    assert result.result_code == "accepted"
    assert result.native_session_id is None
    assert lookups == []
    assert "private response body" not in repr(result)
    assert "private bearer token" not in repr(result)


@pytest.mark.parametrize(
    ("stdout", "evidence_code"),
    [
        ("{}", "resume_identity_missing"),
        ("not-json", "resume_identity_malformed"),
        (json.dumps({"session_id": "not-a-uuid"}), "resume_identity_malformed"),
    ],
)
def test_headless_resume_requires_a_valid_session_identity(
    stdout: str,
    evidence_code: str,
) -> None:
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
            0,
            11,
            stdout=stdout,
            stderr="private bearer token",
        ),
        executable_finder=lambda _name: CLAUDE,
        version_gate=_allow,
    )

    assert result.result_code == "failed"
    assert result.evidence["result_code"] == evidence_code
    assert stdout not in repr(result)
    assert "private bearer token" not in repr(result)


def test_headless_resume_refuses_a_forked_session_identity() -> None:
    forked_session_id = "d00cc889-0000-4000-8000-000000000000"
    stdout = json.dumps(
        {"session_id": forked_session_id, "result": "private fork response"}
    )
    result = run_claude_cli_adapter(
        _context(
            job_kind="wake",
            native_instruction=CHECK_INBOX,
            target_session_id=ACTUAL_ID,
            launch_attestation=None,
            target_liveness="active",
            wake_mode="waiting",
        ),
        process_runner=lambda _invocation: ClaudeProcessResult(0, 13, stdout=stdout),
        executable_finder=lambda _name: CLAUDE,
        version_gate=_allow,
    )

    assert result.result_code == "failed"
    assert result.evidence["result_code"] == "resume_identity_mismatch"
    assert forked_session_id not in repr(result)
    assert "private fork response" not in repr(result)


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


def test_native_runner_uses_the_longer_bound_only_for_headless_wake(
    monkeypatch,
) -> None:
    timeouts = []

    def run(_argv, **kwargs):
        timeouts.append(kwargs["timeout_seconds"])
        return ClaudeProcessResult(0, 1)

    monkeypatch.setattr(claude_module, "run_bounded_claude_process", run)
    launch = ClaudeNativeInvocation(
        CLAUDE,
        Path("/project"),
        ACTUAL_ID,
        "2.1.238",
        "launch instruction",
    )
    wake = ClaudeNativeInvocation(
        CLAUDE,
        Path("/project"),
        ACTUAL_ID,
        "2.1.238",
        CHECK_INBOX,
        resume=True,
    )

    run_claude_process(launch)
    run_claude_process(wake)

    assert timeouts == [
        CLAUDE_NATIVE_TIMEOUT_SECONDS,
        CLAUDE_HEADLESS_WAKE_TIMEOUT_SECONDS,
    ]
    assert CLAUDE_HEADLESS_WAKE_TIMEOUT_SECONDS > CLAUDE_NATIVE_TIMEOUT_SECONDS


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
