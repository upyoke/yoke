"""Closed Claude relay adapter command, version, and redaction tests."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from yoke_harness.session_relay_claude import (
    ClaudeNativeInvocation,
    ClaudeProcessResult,
    run_claude_cli_adapter,
    run_claude_process,
    unsupported_claude_route,
)
from yoke_harness import session_relay_claude as claude_module


LAUNCH_ID = "12345678-1234-4234-8234-123456789abc"
BOOTSTRAP = f"Yoke launch `{LAUNCH_ID}`: register, pull your message, act."
MESSAGE_ID = "message-1"
CHECK_INBOX = f"Yoke message {MESSAGE_ID}: check your Yoke messages."
CLAUDE = "/opt/claude/bin/claude"


def _context(**overrides):
    values = {
        "job_kind": "launch",
        "job_id": LAUNCH_ID,
        "lease_id": "lease-1",
        "surface": "claude-cli",
        "surface_version": "2.1.238",
        "project_id": 10,
        "checkout": Path("/project"),
        "native_instruction": BOOTSTRAP,
        "message_id": MESSAGE_ID,
        "target_session_id": None,
        "launch_attestation": "secret-attestation",
        "model": "claude-opus-4-1",
        "presentation": "focused",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _allow(surface, version, operation):
    assert surface == "claude-cli"
    assert version == "2.1.238"
    assert operation in {"create", "message_stopped"}
    return True


def test_create_stages_attestation_and_binds_launch_id_to_native_session() -> None:
    invocations = []
    handoffs = []

    def runner(invocation):
        invocations.append(invocation)
        return ClaudeProcessResult(
            0,
            17,
            stdout="token-from-native-stdout",
            stderr="secret-from-native-stderr",
        )

    result = run_claude_cli_adapter(
        _context(),
        process_runner=runner,
        executable_finder=lambda _name: CLAUDE,
        version_gate=_allow,
        attestation_handoff=lambda launch_id, secret: (
            handoffs.append((launch_id, secret)) or True
        ),
    )

    assert handoffs == [(LAUNCH_ID, "secret-attestation")]
    assert invocations[0].argv == (
        CLAUDE,
        "--session-id",
        LAUNCH_ID,
        "--model",
        "claude-opus-4-1",
        "--bg",
        BOOTSTRAP,
    )
    assert result.result_code == "native_created"
    assert result.native_session_id == LAUNCH_ID
    assert result.evidence == {
        "result_code": "native_created",
        "surface": "claude-cli",
        "duration_ms": 17,
        "exit_code": 0,
    }
    rendered = repr((invocations[0], result))
    assert "secret-attestation" not in rendered
    assert "token-from-native-stdout" not in rendered
    assert "secret-from-native-stderr" not in rendered


@pytest.mark.parametrize("handoff", [None, lambda _launch_id, _secret: False])
def test_create_fails_closed_before_native_process_without_sidecar(handoff) -> None:
    invocations = []

    result = run_claude_cli_adapter(
        _context(),
        process_runner=invocations.append,
        executable_finder=lambda _name: CLAUDE,
        version_gate=_allow,
        attestation_handoff=handoff,
    )

    assert result.result_code == "not_created"
    assert result.evidence["result_code"] == "attestation_handoff_unavailable"
    assert invocations == []


def test_create_fails_closed_when_shared_context_extensions_are_absent() -> None:
    context = _context()
    del context.model
    invocations = []

    result = run_claude_cli_adapter(
        context,
        process_runner=invocations.append,
        executable_finder=lambda _name: CLAUDE,
        version_gate=_allow,
        attestation_handoff=lambda _launch_id, _secret: True,
    )

    assert result.result_code == "not_created"
    assert result.evidence["result_code"] == "context_incomplete"
    assert invocations == []


def test_create_failure_after_handoff_is_unknown_and_redacted() -> None:
    result = run_claude_cli_adapter(
        _context(),
        process_runner=lambda _invocation: ClaudeProcessResult(
            23,
            81,
            stdout="message body",
            stderr="bearer token",
        ),
        executable_finder=lambda _name: CLAUDE,
        version_gate=_allow,
        attestation_handoff=lambda _launch_id, _secret: True,
    )

    assert result.result_code == "outcome_unknown"
    assert result.evidence == {
        "result_code": "native_exit",
        "surface": "claude-cli",
        "duration_ms": 81,
        "exit_code": 23,
    }
    assert "message body" not in repr(result)
    assert "bearer token" not in repr(result)


def test_wake_resumes_exact_session_at_private_version() -> None:
    invocations = []

    def runner(invocation):
        invocations.append(invocation)
        return ClaudeProcessResult(0, 9)

    result = run_claude_cli_adapter(
        _context(
            job_kind="wake",
            job_id="attempt-1",
            native_instruction=CHECK_INBOX,
            target_session_id="native-session-1",
            launch_attestation=None,
        ),
        process_runner=runner,
        executable_finder=lambda _name: CLAUDE,
        version_gate=_allow,
    )

    assert invocations[0].argv == (
        CLAUDE,
        "--resume",
        "native-session-1",
        "--bg",
        CHECK_INBOX,
    )
    assert result.result_code == "accepted"
    assert result.native_session_id is None
    assert result.evidence["duration_ms"] == 9


def test_private_wake_version_mismatch_never_invokes_native_process() -> None:
    invocations = []
    operations = []

    def reject(_surface, version, operation):
        operations.append((version, operation))
        return False

    result = run_claude_cli_adapter(
        _context(
            job_kind="wake",
            native_instruction=CHECK_INBOX,
            target_session_id="native-session-1",
            surface_version="2.1.239",
        ),
        process_runner=invocations.append,
        executable_finder=lambda _name: CLAUDE,
        version_gate=reject,
    )

    assert result.result_code == "version_mismatch"
    assert result.evidence["result_code"] == "version_mismatch"
    assert operations == [("2.1.239", "message_stopped")]
    assert invocations == []


@pytest.mark.parametrize(
    ("surface", "job_kind", "expected"),
    [
        ("claude-desktop", "launch", "not_created"),
        ("claude-desktop", "wake", "unsupported_surface"),
        ("claude-vscode", "launch", "not_created"),
        ("claude-vscode", "wake", "unsupported_surface"),
    ],
)
def test_desktop_and_vscode_routes_remain_typed_unsupported(
    surface,
    job_kind,
    expected,
) -> None:
    result = unsupported_claude_route(
        _context(surface=surface, job_kind=job_kind),
    )

    assert result.result_code == expected
    assert result.evidence == {
        "result_code": "unsupported_surface",
        "surface": surface,
    }


@pytest.mark.parametrize(
    ("job_kind", "expected"),
    [("launch", "not_created"), ("wake", "failed")],
)
def test_missing_cli_is_discovered_before_native_invocation(
    job_kind,
    expected,
) -> None:
    invocations = []
    result = run_claude_cli_adapter(
        _context(
            job_kind=job_kind,
            native_instruction=BOOTSTRAP if job_kind == "launch" else CHECK_INBOX,
            target_session_id="native-session-1" if job_kind == "wake" else None,
        ),
        process_runner=invocations.append,
        executable_finder=lambda _name: None,
        version_gate=_allow,
        attestation_handoff=lambda _launch_id, _secret: True,
    )

    assert result.result_code == expected
    assert result.evidence["result_code"] == "executable_unavailable"
    assert invocations == []


def test_non_opaque_native_instruction_is_refused_before_discovery() -> None:
    discoveries = []
    result = run_claude_cli_adapter(
        _context(native_instruction="secret body that must not travel natively"),
        executable_finder=lambda name: discoveries.append(name) or CLAUDE,
        version_gate=_allow,
        attestation_handoff=lambda _launch_id, _secret: True,
    )

    assert result.result_code == "not_created"
    assert result.evidence["result_code"] == "instruction_invalid"
    assert discoveries == []


def test_native_process_runner_discards_stdout_and_stderr(monkeypatch) -> None:
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=0)

    monotonic = iter((10.0, 10.012))
    monkeypatch.setattr(claude_module.subprocess, "run", fake_run)
    monkeypatch.setattr(claude_module.time, "monotonic", lambda: next(monotonic))
    invocation = ClaudeNativeInvocation(
        CLAUDE,
        Path("/project"),
        LAUNCH_ID,
        BOOTSTRAP,
    )

    result = run_claude_process(invocation)

    assert calls[0][0] == list(invocation.argv)
    assert calls[0][1]["stdin"] is claude_module.subprocess.DEVNULL
    assert calls[0][1]["stdout"] is claude_module.subprocess.DEVNULL
    assert calls[0][1]["stderr"] is claude_module.subprocess.DEVNULL
    assert result.returncode == 0
    assert result.duration_ms == 12
