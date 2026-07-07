"""Tests for the canonical release failure-mode cases.

Covers the failure-mode disambiguation added to
``release_item_claim_for_execution`` and the matching
``ItemClaimReleaseFailed`` event emission contract:

1. Cross-session release attempt → ``not_owned`` + holder named.
2. Already-terminal release of a previously-released claim → ``already_terminal``.
3. Release of a non-existent item → ``item_not_found``.
4. Happy-path release from owning session → ``released=True`` and **no**
   ``ItemClaimReleaseFailed`` event.

The tests treat the helper as the public surface; CLI exit-code wiring
is covered separately in ``test_service_client_sessions_release_item.py``.
"""

from __future__ import annotations

from unittest.mock import patch

from yoke_core.domain.sessions import (
    claim_work,
    release_item_claim_for_execution,
)
from yoke_core.domain.sessions_lifecycle_release_failure import (
    RELEASE_FAILURE_ALREADY_TERMINAL,
    RELEASE_FAILURE_ITEM_NOT_FOUND,
    RELEASE_FAILURE_NOT_OWNED,
)
from runtime.api.test_sessions import _register, conn  # noqa: F401  (pytest fixture)


_FAILED_EVENT = "ItemClaimReleaseFailed"
_RELEASED_EVENT = "WorkReleased"


def _sun(item_id: int) -> str:
    return f"YOK-{item_id}"


def _emitted_events(mock_emit) -> list[str]:
    """Return the ordered list of event_names the mock saw."""
    return [
        call.kwargs.get("event_name", call.args[0] if call.args else None)
        for call in mock_emit.call_args_list
    ]


def _event_context(mock_emit, event_name: str) -> dict:
    for call in mock_emit.call_args_list:
        seen = call.kwargs.get("event_name", call.args[0] if call.args else None)
        if seen == event_name:
            return call.kwargs["context"]
    raise AssertionError(f"event not emitted: {event_name}")


class TestReleaseFailureModes:
    """Four canonical release result cases."""

    def test_cross_session_release_returns_not_owned_with_holder(self, conn):
        owner_sid = "owner-sess"
        intruder_sid = "intruder-sess"
        item_id = 700
        _register(conn, session_id=owner_sid)
        _register(conn, session_id=intruder_sid)
        claim_work(conn, session_id=owner_sid, item_id=_sun(item_id))

        with patch(
            "yoke_core.domain.sessions_analytics._emit_event",
        ) as mock_emit:
            result = release_item_claim_for_execution(
                conn, intruder_sid, _sun(item_id), "handoff-to-polish",
            )

        assert result["released"] is False
        assert result["failure_reason"] == RELEASE_FAILURE_NOT_OWNED
        assert result["holder_session_id"] == owner_sid
        assert result["reason_intent"] == "handoff-to-polish"

        events = _emitted_events(mock_emit)
        assert _FAILED_EVENT in events
        assert _RELEASED_EVENT not in events
        ctx = _event_context(mock_emit, _FAILED_EVENT)
        assert ctx["item_id"] == str(item_id)
        assert ctx["caller_session_id"] == intruder_sid
        assert ctx["holder_session_id"] == owner_sid
        assert ctx["failure_reason"] == RELEASE_FAILURE_NOT_OWNED
        assert ctx["target_status"] is None
        assert ctx["release_reason_intent"] == "handoff-to-polish"

        # Original claim untouched.
        row = conn.execute(
            "SELECT released_at FROM work_claims WHERE session_id=%s "
            "AND item_id='700'",
            (owner_sid,),
        ).fetchone()
        assert row["released_at"] is None

    def test_already_terminal_release_returns_already_terminal(self, conn):
        owner_sid = "owner-already-terminal"
        item_id = 710
        _register(conn, session_id=owner_sid)
        claim_work(conn, session_id=owner_sid, item_id=_sun(item_id))
        # First release succeeds.
        first = release_item_claim_for_execution(
            conn, owner_sid, _sun(item_id), "finalize-exit",
        )
        assert first["released"] is True

        with patch(
            "yoke_core.domain.sessions_analytics._emit_event",
        ) as mock_emit:
            second = release_item_claim_for_execution(
                conn, owner_sid, _sun(item_id), "finalize-exit",
            )

        assert second["released"] is False
        assert second["failure_reason"] == RELEASE_FAILURE_ALREADY_TERMINAL
        assert second["holder_session_id"] == owner_sid

        events = _emitted_events(mock_emit)
        assert _FAILED_EVENT in events
        assert _RELEASED_EVENT not in events

    def test_item_never_claimed_returns_item_not_found(self, conn):
        sid = "never-claimed-sess"
        item_id = 9999
        _register(conn, session_id=sid)

        with patch(
            "yoke_core.domain.sessions_analytics._emit_event",
        ) as mock_emit:
            result = release_item_claim_for_execution(
                conn, sid, _sun(item_id), "handoff-to-usher",
            )

        assert result["released"] is False
        assert result["failure_reason"] == RELEASE_FAILURE_ITEM_NOT_FOUND
        assert result["holder_session_id"] is None

        events = _emitted_events(mock_emit)
        assert _FAILED_EVENT in events
        assert _RELEASED_EVENT not in events

    def test_happy_path_release_emits_no_failure_event(self, conn):
        owner_sid = "happy-sess"
        item_id = 720
        _register(conn, session_id=owner_sid)
        claim_work(conn, session_id=owner_sid, item_id=_sun(item_id))

        with patch(
            "yoke_core.domain.sessions_analytics._emit_event",
        ) as mock_emit:
            result = release_item_claim_for_execution(
                conn, owner_sid, _sun(item_id), "handoff-to-polish",
            )

        assert result["released"] is True
        events = _emitted_events(mock_emit)
        # Happy path emits nothing new — only WorkReleased.
        assert _RELEASED_EVENT in events
        assert _FAILED_EVENT not in events
