"""A held session survives the idle cleanup that reaps an empty one."""

import pytest

from runtime.api.test_sessions import _register
from yoke_core.domain.session_keepalive import (
    hold_session_keepalive,
    release_session_keepalive,
    session_keepalive_holds,
)
from yoke_core.domain.session_message_types import timestamp, utc_now
from yoke_core.domain.sessions import end_session_if_empty
from yoke_core.domain.sessions_analytics import SessionError
from yoke_contracts.session_control.keepalive import MAX_KEEPALIVE_SECONDS

pytest_plugins = ("runtime.api.test_sessions",)


def _ended_at(conn, session_id: str):
    return conn.execute(
        "SELECT ended_at FROM harness_sessions WHERE session_id = %s",
        (session_id,),
    ).fetchone()["ended_at"]


def test_held_session_is_not_reaped_while_it_holds_nothing_else(conn):
    _register(conn, session_id="held-broker")
    hold_session_keepalive(
        conn, "held-broker", seconds=600, reason="acceptance broker"
    )

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
