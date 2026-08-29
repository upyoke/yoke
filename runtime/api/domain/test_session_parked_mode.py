# ruff: noqa: F811
"""Stamp parked with a reason, refuse unknown modes, persist across tool calls."""

from __future__ import annotations

from runtime.api.test_sessions import _register, conn  # noqa: F401
from yoke_core.domain.session_activity_state import apply_envelope_state
from yoke_core.domain.session_mode import (
    SESSION_MODE_DEFAULT,
    SESSION_MODE_PARKED,
    SESSION_MODES,
    set_session_mode,
)
from yoke_core.domain.sessions import SessionError


def test_set_session_mode_stamps_parked_with_reason(conn):
    _register(conn)
    result = set_session_mode(
        conn, "sess-1", SESSION_MODE_PARKED, reason="waiting on YOK-2546"
    )
    assert result["mode"] == SESSION_MODE_PARKED
    assert result["parked_reason"] == "waiting on YOK-2546"
    row = conn.execute(
        "SELECT mode, parked_reason FROM harness_sessions WHERE session_id = 'sess-1'"
    ).fetchone()
    assert row["mode"] == SESSION_MODE_PARKED
    assert row["parked_reason"] == "waiting on YOK-2546"


def test_reason_on_a_non_parked_mode_is_refused(conn):
    _register(conn)
    try:
        set_session_mode(conn, "sess-1", "dash", reason="nope")
    except SessionError as exc:
        assert exc.code == "REASON_REQUIRES_PARKED"
    else:
        raise AssertionError("expected REASON_REQUIRES_PARKED")


def test_parked_without_reason_is_refused(conn):
    _register(conn)
    try:
        set_session_mode(conn, "sess-1", SESSION_MODE_PARKED)
    except SessionError as exc:
        assert exc.code == "PARKED_REASON_REQUIRED"
    else:
        raise AssertionError("expected PARKED_REASON_REQUIRED")


def test_unknown_mode_is_refused_with_accepted_values(conn):
    _register(conn)
    try:
        set_session_mode(conn, "sess-1", "napping")
    except SessionError as exc:
        assert exc.code == "UNKNOWN_MODE"
        assert SESSION_MODE_PARKED in exc.message
        assert SESSION_MODE_DEFAULT in exc.message
        for accepted in sorted(SESSION_MODES):
            assert accepted in exc.message
    else:
        raise AssertionError("expected UNKNOWN_MODE")


def test_a_tool_call_does_not_clear_parked(conn):
    _register(conn)
    set_session_mode(conn, "sess-1", SESSION_MODE_PARKED, reason="waiting")
    apply_envelope_state(
        conn,
        {
            "event_name": "HarnessToolCallStarted",
            "session_id": "sess-1",
            "event_time": "2026-08-27T20:00:00Z",
            "tool_use_id": "tool-1",
            "tool_name": "Shell",
        },
    )
    row = conn.execute(
        "SELECT mode, parked_reason FROM harness_sessions WHERE session_id = 'sess-1'"
    ).fetchone()
    assert row["mode"] == SESSION_MODE_PARKED
    assert row["parked_reason"] == "waiting"


def test_stamping_a_working_mode_clears_parked(conn):
    _register(conn)
    set_session_mode(conn, "sess-1", SESSION_MODE_PARKED, reason="waiting")
    set_session_mode(conn, "sess-1", "dash")
    row = conn.execute(
        "SELECT mode, parked_reason FROM harness_sessions WHERE session_id = 'sess-1'"
    ).fetchone()
    assert row["mode"] == "dash"
    assert row["parked_reason"] is None
