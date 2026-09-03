"""Claude launch correlation through control-plane registration."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from yoke_contracts.session_control.launch_bootstrap import native_launch_bootstrap
from yoke_harness.session_relay_claude import run_claude_cli_adapter
from yoke_harness.session_relay_claude_process import ClaudeProcessResult
from yoke_harness.session_relay_claude_registration import (
    resolve_registered_session,
)


LAUNCH_ID = "12345678-1234-4234-8234-123456789abc"
SESSION_ID = "87654321-4321-4321-8321-cba987654321"
SHORT_ID = "7c5dcf5d"


def _context(resolver):
    return SimpleNamespace(
        job_kind="launch",
        job_id=LAUNCH_ID,
        lease_id="lease-1",
        surface="claude-cli",
        surface_version="2.1.238",
        project_id=10,
        checkout=Path("/project"),
        native_instruction=native_launch_bootstrap(LAUNCH_ID),
        message_id="message-1",
        target_session_id=None,
        launch_attestation="secret-attestation",
        requested_model=None,
        presentation="local",
        session_name=None,
        launch_deadline_at="2099-08-22T12:15:00Z",
        launch_progress_reporter=None,
        launch_registration_resolver=resolver,
        target_liveness=None,
        wake_mode=None,
    )


def test_listing_lag_binds_the_session_that_registered_for_the_launch() -> None:
    resolver_calls = []
    handoffs = []

    def resolve(workspace):
        resolver_calls.append(workspace)
        return {"status": "registered_but_unbound", "session_id": SESSION_ID}

    result = run_claude_cli_adapter(
        _context(resolve),
        process_runner=lambda _invocation: ClaudeProcessResult(
            0,
            17,
            f"backgrounded · {SHORT_ID} · Example session",
        ),
        session_lookup=lambda _invocation: ClaudeProcessResult(0, 7, json.dumps([])),
        executable_finder=lambda _name: "/opt/claude/bin/claude",
        version_gate=lambda _surface, _version, _operation: True,
        attestation_handoff=lambda *_args, **kwargs: handoffs.append(kwargs) or True,
    )

    assert resolver_calls == ["/project"]
    assert handoffs == []
    assert result.result_code == "native_created"
    assert result.native_session_id == SESSION_ID
    assert result.evidence["result_code"] == "registered_but_unbound"


def test_registration_resolution_retries_a_pending_candidate() -> None:
    responses = iter(
        (
            {"status": "registration_pending"},
            {"status": "registered_but_unbound", "session_id": SESSION_ID},
        )
    )

    result = resolve_registered_session(lambda _workspace: next(responses), "/project")

    assert result.session_id == SESSION_ID
    assert result.result_code == "registered_but_unbound"
    assert result.attempts == 2
