"""Claude background identity, transport, version, and redaction tests."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from yoke_contracts.session_control.launch_bootstrap import native_launch_bootstrap
from yoke_contracts.session_control.wake_instruction import native_wake_instruction
from yoke_harness import session_relay_claude_native as claude_native_module
from yoke_harness.session_launch_handoff import LAUNCH_CONTEXT_ENV
from yoke_harness.session_relay_claude import (
    ClaudeNativeInvocation,
    ClaudeProcessResult,
    lookup_claude_session,
    run_claude_cli_adapter,
    run_claude_process,
    unsupported_claude_route,
)


LAUNCH_ID = "12345678-1234-4234-8234-123456789abc"
ACTUAL_ID = "87654321-4321-4321-8321-cba987654321"
SHORT_ID = "7c5dcf5d"
BOOTSTRAP = native_launch_bootstrap(LAUNCH_ID)
MESSAGE_ID = "message-1"
CHECK_INBOX = native_wake_instruction(MESSAGE_ID)
CLAUDE = "/opt/claude/bin/claude"
CLAUDE_LOCAL_SETTINGS_JSON = '{"disableRemoteControl":true}'


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
        "requested_model": "claude-opus-4-1",
        "presentation": "local",
        "session_name": "YOK-2580: Record session presentation",
        "target_liveness": None,
        "wake_mode": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _allow(surface, version, operation):
    assert surface == "claude-cli"
    assert version == "2.1.238"
    assert operation in {"create", "message_active", "message_idle", "message_stopped"}
    return True


def _created(output: str | None = None) -> ClaudeProcessResult:
    return ClaudeProcessResult(
        0,
        17,
        output or f"backgrounded · {SHORT_ID}\nclaude attach {SHORT_ID}",
        "private-create-stderr",
    )


def _agents(rows=None, *, returncode: int = 0) -> ClaudeProcessResult:
    document = rows if rows is not None else [{"id": SHORT_ID, "sessionId": ACTUAL_ID}]
    return ClaudeProcessResult(
        returncode,
        7,
        json.dumps(document) if not isinstance(document, str) else document,
        "private-lookup-stderr",
    )


def test_create_reports_and_stages_the_actual_background_session() -> None:
    invocations = []
    lookups = []
    handoffs = []

    def handoff(launch_id, secret, **kwargs):
        handoffs.append((launch_id, secret, kwargs))
        return True

    result = run_claude_cli_adapter(
        _context(),
        process_runner=lambda invocation: invocations.append(invocation) or _created(),
        session_lookup=lambda invocation: lookups.append(invocation) or _agents(),
        executable_finder=lambda _name: CLAUDE,
        version_gate=_allow,
        attestation_handoff=handoff,
    )

    assert invocations[0].argv == (
        CLAUDE,
        "--session-id",
        LAUNCH_ID,
        "--dangerously-skip-permissions",
        "--settings",
        CLAUDE_LOCAL_SETTINGS_JSON,
        "--model",
        "claude-opus-4-1",
        "--name",
        "YOK-2580: Record session presentation",
        "--bg",
        BOOTSTRAP,
    )
    assert lookups == invocations
    assert handoffs == [(LAUNCH_ID, "secret-attestation", {"binding_id": ACTUAL_ID})]
    assert ACTUAL_ID != LAUNCH_ID
    assert result.result_code == "native_created"
    assert result.native_session_id == ACTUAL_ID
    assert result.evidence["result_code"] == "native_created"
    assert result.evidence["presentation_preference"] == "local"
    assert result.evidence["presentation_control"] == "disableRemoteControl"
    assert "private-create-stderr" not in repr(result.evidence)
    assert "private-lookup-stderr" not in repr(result.evidence)
    assert "secret-attestation" not in repr(invocations[0])


@pytest.mark.parametrize(
    ("created", "lookup", "code"),
    [
        (_created("no background identity"), _agents(), "identity_parse_failed"),
        (_created(), _agents(returncode=8), "identity_lookup_failed"),
        (_created(), _agents("not-json"), "identity_parse_failed"),
        (
            _created(),
            _agents([{"id": "another", "sessionId": ACTUAL_ID}]),
            "identity_parse_failed",
        ),
        (
            _created(),
            _agents([{"id": SHORT_ID, "sessionId": "not-a-uuid"}]),
            "identity_parse_failed",
        ),
    ],
)
def test_create_identity_failures_are_unknown_and_private(
    created, lookup, code
) -> None:
    lookup_calls = []
    handoffs = []
    result = run_claude_cli_adapter(
        _context(),
        process_runner=lambda _invocation: created,
        session_lookup=lambda invocation: lookup_calls.append(invocation) or lookup,
        executable_finder=lambda _name: CLAUDE,
        version_gate=_allow,
        attestation_handoff=lambda *_args, **kwargs: handoffs.append(kwargs) or True,
    )

    assert result.result_code == "outcome_unknown"
    assert result.native_session_id is None
    assert result.evidence["result_code"] == code
    assert handoffs == []
    assert len(lookup_calls) == (0 if created.stdout == "no background identity" else 4)
    assert "private" not in repr(result.evidence)
    if created.stdout == "no background identity":
        assert result.private_diagnostic is not None
        assert result.private_diagnostic.stdout == b"no background identity"


def test_lookup_exception_text_never_enters_result() -> None:
    def unavailable(_invocation):
        raise RuntimeError("secret lookup output")

    result = run_claude_cli_adapter(
        _context(),
        process_runner=lambda _invocation: _created(),
        session_lookup=unavailable,
        executable_finder=lambda _name: CLAUDE,
        version_gate=_allow,
        attestation_handoff=lambda *_args, **_kwargs: True,
    )

    assert result.result_code == "outcome_unknown"
    assert result.evidence["result_code"] == "identity_lookup_failed"
    assert "secret lookup output" not in repr(result)


def test_sidecar_failure_reports_known_actual_session_as_unknown() -> None:
    handoffs = []
    result = run_claude_cli_adapter(
        _context(),
        process_runner=lambda _invocation: _created(),
        session_lookup=lambda _invocation: _agents(),
        executable_finder=lambda _name: CLAUDE,
        version_gate=_allow,
        attestation_handoff=lambda *_args, **kwargs: handoffs.append(kwargs) or False,
    )

    assert handoffs == [{"binding_id": ACTUAL_ID}]
    assert result.result_code == "outcome_unknown"
    assert result.native_session_id == ACTUAL_ID
    assert result.evidence["result_code"] == "attestation_handoff_failed"


def test_missing_sidecar_refuses_before_native_create() -> None:
    calls = []
    result = run_claude_cli_adapter(
        _context(),
        process_runner=calls.append,
        executable_finder=lambda _name: CLAUDE,
        version_gate=_allow,
    )

    assert result.result_code == "not_created"
    assert result.evidence["result_code"] == "attestation_handoff_unavailable"
    assert calls == []


def test_native_commands_use_private_collector_without_launch_secret(
    monkeypatch,
) -> None:
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return ClaudeProcessResult(0, 12, "private-stdout", "private-stderr")

    monkeypatch.setattr(
        claude_native_module,
        "run_bounded_claude_process",
        fake_run,
    )
    monkeypatch.setenv("CODEX_SESSION_ID", "parent-session")
    invocation = ClaudeNativeInvocation(
        CLAUDE,
        Path("/project"),
        LAUNCH_ID,
        "2.1.238",
        BOOTSTRAP,
    )

    created = run_claude_process(invocation)
    agents = lookup_claude_session(invocation)

    assert calls[0][0] == invocation.argv
    assert calls[1][0] == (CLAUDE, "agents", "--all", "--json")
    assert "CODEX_SESSION_ID" not in calls[0][1]["environment"]
    assert LAUNCH_CONTEXT_ENV not in calls[0][1]["environment"]
    assert calls[0][1]["timeout_seconds"] == 20
    assert "private" not in repr((created, agents))


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
    assert result.evidence["result_code"] == "native_exit"
    assert result.evidence["presentation_control"] == "disableRemoteControl"
    assert "message body" not in repr(result)
    assert "bearer token" not in repr(result)


@pytest.mark.parametrize(
    ("surface", "job_kind", "expected"),
    [
        ("claude-desktop", "launch", "not_created"),
        ("claude-desktop", "wake", "unsupported_surface"),
        ("claude-vscode", "launch", "not_created"),
        ("claude-vscode", "wake", "unsupported_surface"),
    ],
)
def test_desktop_and_vscode_routes_remain_typed(surface, job_kind, expected) -> None:
    result = unsupported_claude_route(_context(surface=surface, job_kind=job_kind))
    assert result.result_code == expected
    assert result.evidence["result_code"] == "unsupported_surface"


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
            target_liveness="ended" if job_kind == "wake" else None,
            wake_mode="waiting" if job_kind == "wake" else None,
        ),
        process_runner=invocations.append,
        executable_finder=lambda _name: None,
        version_gate=_allow,
        attestation_handoff=lambda _launch_id, _secret: True,
    )

    assert result.result_code == expected
    assert result.evidence["result_code"] == "executable_unavailable"
    assert invocations == []


@pytest.mark.parametrize(
    ("context", "code"),
    [
        (_context(native_instruction="secret body"), "instruction_invalid"),
        (
            _context(
                job_id="not-a-uuid",
                native_instruction=(native_launch_bootstrap("not-a-uuid")),
            ),
            "native_session_invalid",
        ),
    ],
)
def test_invalid_launch_inputs_are_refused_before_native_process(context, code) -> None:
    calls = []
    result = run_claude_cli_adapter(
        context,
        process_runner=calls.append,
        executable_finder=lambda _name: CLAUDE,
        version_gate=_allow,
        attestation_handoff=lambda *_args, **_kwargs: True,
    )

    assert result.result_code == "not_created"
    assert result.evidence["result_code"] == code
    assert calls == []
