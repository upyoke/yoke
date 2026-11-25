"""A held session survives the idle cleanup that reaps an empty one."""

from runtime.api.sessions_test_support import conn as conn  # noqa: F401

import pytest

from runtime.api.sessions_test_support import _register
from yoke_core.domain.session_keepalive import (
    hold_session_keepalive,
    release_session_keepalive,
    session_keepalive_holds,
)
from yoke_core.domain.session_message_types import timestamp, utc_now
from yoke_core.domain.sessions import end_session_if_empty
from yoke_core.domain.sessions_analytics import SessionError
from yoke_contracts.session_control.keepalive import MAX_KEEPALIVE_SECONDS


def _ended_at(conn, session_id: str):
    return conn.execute(
        "SELECT ended_at FROM harness_sessions WHERE session_id = %s",
        (session_id,),
    ).fetchone()["ended_at"]


def test_held_session_is_not_reaped_while_it_holds_nothing_else(conn):
    _register(conn, session_id="held-broker")
    hold_session_keepalive(conn, "held-broker", seconds=600, reason="acceptance broker")

    result = end_session_if_empty(conn, "held-broker")

    assert result["ended"] is False
    assert result["status"] == "keepalive_held"
    assert result["keepalive_reason"] == "acceptance broker"
    assert result["keepalive_until"]
    assert _ended_at(conn, "held-broker") is None


def test_expired_hold_no_longer_protects_the_session(conn):
    _register(conn, session_id="expired-hold")
    hold_session_keepalive(conn, "expired-hold", seconds=600, reason="stale")
    conn.execute(
        "UPDATE harness_sessions SET keepalive_until = %s WHERE session_id = %s",
        (timestamp(utc_now().replace(year=utc_now().year - 1)), "expired-hold"),
    )
    conn.commit()

    assert session_keepalive_holds(conn, ("expired-hold",)) == {}
    result = end_session_if_empty(conn, "expired-hold")

    assert result["ended"] is True
    assert _ended_at(conn, "expired-hold") is not None


def test_released_hold_returns_the_session_to_ordinary_cleanup(conn):
    _register(conn, session_id="released-hold")
    hold_session_keepalive(conn, "released-hold", seconds=600, reason="broker")

    assert release_session_keepalive(conn, "released-hold") is True
    assert release_session_keepalive(conn, "released-hold") is False
    result = end_session_if_empty(conn, "released-hold")

    assert result["ended"] is True


def test_a_hold_states_why_and_bounds_its_own_window(conn):
    _register(conn, session_id="guarded-hold")

    with pytest.raises(SessionError) as blank:
        hold_session_keepalive(conn, "guarded-hold", seconds=60, reason="   ")
    assert blank.value.code == "KEEPALIVE_REASON_REQUIRED"

    with pytest.raises(SessionError) as unbounded:
        hold_session_keepalive(
            conn,
            "guarded-hold",
            seconds=MAX_KEEPALIVE_SECONDS + 1,
            reason="forever",
        )
    assert unbounded.value.code == "KEEPALIVE_WINDOW_INVALID"


def test_holding_an_ended_session_refuses_with_its_recovery(conn):
    _register(conn, session_id="gone-already")
    end_session_if_empty(conn, "gone-already")

    with pytest.raises(SessionError) as ended:
        hold_session_keepalive(conn, "gone-already", seconds=60, reason="too late")

    assert ended.value.code == "SESSION_ENDED"
    assert "yoke sessions begin" in ended.value.message


def test_stale_sweep_preserves_held_session_and_receipt_until_expiry(conn, monkeypatch):
    from datetime import timedelta

    from runtime.api.fixtures.session_reclaim_messages import (
        message_receipt,
        pending_message,
        start_message_attempt,
    )
    from yoke_core.domain import sessions_analytics
    from yoke_core.domain.sessions_cleanup import clean_stale_harness_sessions
    from yoke_core.domain.sessions_render_reclaim import find_stale_sessions

    session_id = "stale-held"
    _register(conn, session_id=session_id, mode="parked")
    hold_session_keepalive(conn, session_id, seconds=600, reason="await a wake")
    now = utc_now()
    conn.execute(
        "UPDATE harness_sessions SET last_heartbeat=%s WHERE session_id=%s",
        (now - timedelta(days=2), session_id),
    )
    message_id = pending_message(conn, session_id)
    start_message_attempt(conn, message_id, session_id, kind="hook", started_at=now)
    conn.commit()
    aborted = []

    def capture(name, *, session_id, context=None, **_kwargs):
        if name == "ReclaimAborted":
            aborted.append((session_id, context["abort_reason"]))

    monkeypatch.setattr(sessions_analytics, "_emit_session_event", capture)
    assert session_id not in {row["session_id"] for row in find_stale_sessions(conn)}
    assert clean_stale_harness_sessions(conn, project_ids=[1])["total_reclaimed"] == 0
    assert aborted == [(session_id, "keepalive_held")]
    assert _ended_at(conn, session_id) is None
    assert message_receipt(conn, message_id)["state"] == "pending"

    conn.execute(
        "UPDATE harness_sessions SET keepalive_until=%s WHERE session_id=%s",
        (now - timedelta(seconds=1), session_id),
    )
    conn.commit()

    assert clean_stale_harness_sessions(conn, project_ids=[1])["total_reclaimed"] == 1
    assert _ended_at(conn, session_id) is not None
    assert message_receipt(conn, message_id)["state"] == "cancelled"
    attempt = conn.execute(
        "SELECT result_code FROM session_message_attempts WHERE message_id=%s",
        (message_id,),
    ).fetchone()
    assert attempt["result_code"] == "session_reclaimed"
