"""Claude background-agent identity convergence tests."""

from __future__ import annotations

import json

from yoke_harness.session_relay_claude_identity import (
    CLAUDE_IDENTITY_LOOKUP_ATTEMPTS,
    resolve_background_agent,
    resolve_background_session,
)
from yoke_harness.session_relay_claude_process import ClaudeProcessResult


SHORT_ID = "7c5dcf5d"
ACTUAL_ID = "87654321-4321-4321-8321-cba987654321"


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


def test_reverse_lookup_resolves_background_agent_from_native_session_id() -> None:
    resolution = resolve_background_agent(
        ACTUAL_ID,
        lambda: _agents(ACTUAL_ID, status="completed"),
    )

    assert resolution.short_id == SHORT_ID
    assert resolution.result_code == "background_agent_resolved"
    assert resolution.attempts == 1
    assert resolution.duration_ms == 7


def test_reverse_lookup_distinguishes_foreground_session_from_invalid_listing() -> None:
    foreground = resolve_background_agent(
        ACTUAL_ID,
        lambda: _agents(
            "11111111-1111-4111-8111-111111111111",
            status="completed",
        ),
        attempts=1,
    )
    invalid = resolve_background_agent(
        ACTUAL_ID,
        lambda: ClaudeProcessResult(0, 7, "not-json"),
        attempts=1,
    )

    assert foreground.short_id is None
    assert foreground.result_code == "background_agent_not_found"
    assert foreground.attempts == 1
    assert invalid.short_id is None
    assert invalid.result_code == "identity_parse_failed"
