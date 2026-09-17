# ruff: noqa: F811
"""Stamp session modes with reasons and preserve parked-mode semantics."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from runtime.api.test_sessions import _register, conn  # noqa: F401
from yoke_core.domain.session_activity_state import apply_envelope_state
from yoke_core.domain.session_mode import (
    SESSION_MODE_DEFAULT,
    SESSION_MODE_PARKED,
    SESSION_MODES,
    set_session_mode,
)
from yoke_core.domain.sessions import SessionError, heartbeat
from yoke_core.hooks.session_turn_posture_tail import persist_accepted_hook_turn_posture

def _after_registration(seconds=1):
    return datetime.now(timezone.utc) + timedelta(seconds=seconds)


def _shared_factory(conn, monkeypatch):
    monkeypatch.setattr(conn, "close", lambda: None)
    return lambda: conn


def _ensure_turn_posture(conn):
    conn.execute(
        "ALTER TABLE harness_sessions "
        "ADD COLUMN IF NOT EXISTS turn_posture TEXT NOT NULL DEFAULT 'unknown'"
    )
    conn.execute(
        "ALTER TABLE harness_sessions "
        "ADD COLUMN IF NOT EXISTS turn_posture_at TEXT DEFAULT NULL"
    )
    conn.commit()


def test_set_session_mode_stamps_parked_with_reason(conn):
    _register(conn)
    result = set_session_mode(
        conn, "sess-1", SESSION_MODE_PARKED, reason="waiting on a blocking claim"
    )
    assert result["mode"] == SESSION_MODE_PARKED
    assert result["quiet_reason"] == "waiting on a blocking claim"
    row = conn.execute(
        "SELECT mode, quiet_reason FROM harness_sessions WHERE session_id = 'sess-1'"
    ).fetchone()
    assert row["mode"] == SESSION_MODE_PARKED
    assert row["quiet_reason"] == "waiting on a blocking claim"


def test_reason_on_a_working_mode_is_persisted(conn):
    _register(conn)
    result = set_session_mode(conn, "sess-1", "dash", reason="waiting on CI")

    assert result["mode"] == "dash"
    assert result["quiet_reason"] == "waiting on CI"


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
        "SELECT mode, quiet_reason FROM harness_sessions WHERE session_id = 'sess-1'"
    ).fetchone()
    assert row["mode"] == SESSION_MODE_PARKED
    assert row["quiet_reason"] == "waiting"


def test_stamping_a_working_mode_clears_parked(conn):
    _register(conn)
    set_session_mode(conn, "sess-1", SESSION_MODE_PARKED, reason="waiting")
    set_session_mode(conn, "sess-1", "dash")
    row = conn.execute(
        "SELECT mode, quiet_reason FROM harness_sessions WHERE session_id = 'sess-1'"
    ).fetchone()
    assert row["mode"] == "dash"
    assert row["quiet_reason"] is None


def _parked_row(conn):
    return conn.execute(
        "SELECT mode, quiet_reason FROM harness_sessions WHERE session_id = 'sess-1'"
    ).fetchone()


def test_accepted_prompt_submit_clears_parked(conn, monkeypatch):
    _register(conn)
    _ensure_turn_posture(conn)
    set_session_mode(conn, "sess-1", SESSION_MODE_PARKED, reason="awaiting superseded decisions")
    assert persist_accepted_hook_turn_posture(
        event_name="UserPromptSubmit",
        session_id="sess-1",
        observed_at=_after_registration(),
        final_outcome="allow",
        timed_out=False,
        failed=False,
        connection_factory=_shared_factory(conn, monkeypatch),
    )
    row = _parked_row(conn)
    assert row["mode"] == SESSION_MODE_DEFAULT
    assert row["quiet_reason"] is None


def test_failed_or_denied_prompt_submit_does_not_clear_parked(conn, monkeypatch):
    _register(conn)
    set_session_mode(conn, "sess-1", SESSION_MODE_PARKED, reason="waiting")
    for outcome, failed in (("deny", False), ("allow", True)):
        assert not persist_accepted_hook_turn_posture(
            event_name="UserPromptSubmit",
            session_id="sess-1",
            observed_at=_after_registration(),
            final_outcome=outcome,
            timed_out=False,
            failed=failed,
            connection_factory=_shared_factory(conn, monkeypatch),
        )
    row = _parked_row(conn)
    assert row["mode"] == SESSION_MODE_PARKED
    assert row["quiet_reason"] == "waiting"


def test_heartbeat_and_stop_do_not_clear_parked(conn, monkeypatch):
    _register(conn)
    _ensure_turn_posture(conn)
    set_session_mode(conn, "sess-1", SESSION_MODE_PARKED, reason="waiting")
    heartbeat(conn, "sess-1")
    assert persist_accepted_hook_turn_posture(
        event_name="Stop",
        session_id="sess-1",
        observed_at=_after_registration(),
        final_outcome="allow",
        timed_out=False,
        failed=False,
        connection_factory=_shared_factory(conn, monkeypatch),
    )
    row = _parked_row(conn)
    assert row["mode"] == SESSION_MODE_PARKED
    assert row["quiet_reason"] == "waiting"


def test_stale_prompt_submit_does_not_clear_a_later_repark(conn, monkeypatch):
    _register(conn)
    _ensure_turn_posture(conn)
    set_session_mode(conn, "sess-1", SESSION_MODE_PARKED, reason="waiting")
    first = _after_registration(seconds=10)
    assert persist_accepted_hook_turn_posture(
        event_name="UserPromptSubmit",
        session_id="sess-1",
        observed_at=first,
        final_outcome="allow",
        timed_out=False,
        failed=False,
        connection_factory=_shared_factory(conn, monkeypatch),
    )
    set_session_mode(conn, "sess-1", SESSION_MODE_PARKED, reason="waiting on operator")
    assert not persist_accepted_hook_turn_posture(
        event_name="UserPromptSubmit",
        session_id="sess-1",
        observed_at=first - timedelta(seconds=5),
        final_outcome="allow",
        timed_out=False,
        failed=False,
        connection_factory=_shared_factory(conn, monkeypatch),
    )
    row = _parked_row(conn)
    assert row["mode"] == SESSION_MODE_PARKED
    assert row["quiet_reason"] == "waiting on operator"


def test_delayed_prompt_does_not_clear_a_newer_park_write(conn, monkeypatch):
    _register(conn)
    _ensure_turn_posture(conn)
    from yoke_core.domain.session_turn_posture import posture_timestamp

    previous = datetime.now(timezone.utc) - timedelta(seconds=30)
    prompt_observed = previous + timedelta(seconds=10)
    stamp = posture_timestamp(previous)
    conn.execute(
        "UPDATE harness_sessions SET turn_posture = 'waiting', "
        f"turn_posture_at = '{stamp}' WHERE session_id = 'sess-1'"
    )
    conn.commit()
    set_session_mode(conn, "sess-1", SESSION_MODE_PARKED, reason="waiting on operator")
    assert not persist_accepted_hook_turn_posture(
        event_name="UserPromptSubmit",
        session_id="sess-1",
        observed_at=prompt_observed,
        final_outcome="allow",
        timed_out=False,
        failed=False,
        connection_factory=_shared_factory(conn, monkeypatch),
    )
    row = _parked_row(conn)
    assert row["mode"] == SESSION_MODE_PARKED
    assert row["quiet_reason"] == "waiting on operator"
