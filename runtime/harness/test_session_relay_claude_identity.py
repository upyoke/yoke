"""Claude background-agent identity convergence tests."""

from __future__ import annotations

import json

from yoke_harness.session_relay_claude_identity import (
    CLAUDE_IDENTITY_LOOKUP_ATTEMPTS,
    background_agent_id,
    resolve_background_session,
)
from yoke_harness.session_relay_claude_process import ClaudeProcessResult


SHORT_ID = "7c5dcf5d"
ACTUAL_ID = "87654321-4321-4321-8321-cba987654321"


def test_background_identity_accepts_named_display_suffix() -> None:
    process = ClaudeProcessResult(
        0,
        7,
        f"backgrounded · {SHORT_ID} · proof-target (idle — send a prompt to start)",
    )

    assert background_agent_id(process) == SHORT_ID


def test_background_identity_rejects_unseparated_trailing_text() -> None:
    process = ClaudeProcessResult(0, 7, f"backgrounded · {SHORT_ID} ambiguous")

    assert background_agent_id(process) is None


def _agents(session_id, *, status: str) -> ClaudeProcessResult:
    return ClaudeProcessResult(
        0,
        7,
        json.dumps(
            {
                "agents": [
                    {
                        "id": SHORT_ID,
                        "sessionId": session_id,
                        "status": status,
                    }
                ]
            }
        ),
    )


def test_lookup_retries_until_completed_agent_has_full_session_id() -> None:
    listings = iter(
        (
            _agents(None, status="running"),
            _agents(ACTUAL_ID, status="completed"),
        )
    )
    delays = []

    resolution = resolve_background_session(
        SHORT_ID,
        lambda: next(listings),
        sleeper=delays.append,
    )

    assert resolution.session_id == ACTUAL_ID
    assert resolution.result_code == "identity_resolved"
    assert resolution.attempts == 2
    assert resolution.duration_ms == 14
    assert delays == [0.1]


def test_lookup_fails_closed_after_bounded_missing_session_id_window() -> None:
    calls = []
    delays = []

    resolution = resolve_background_session(
        SHORT_ID,
        lambda: calls.append(True) or _agents(None, status="completed"),
        sleeper=delays.append,
    )

    assert resolution.session_id is None
    assert resolution.result_code == "identity_parse_failed"
    assert resolution.attempts == CLAUDE_IDENTITY_LOOKUP_ATTEMPTS
    assert len(calls) == CLAUDE_IDENTITY_LOOKUP_ATTEMPTS
    assert len(delays) == CLAUDE_IDENTITY_LOOKUP_ATTEMPTS - 1
