"""Wake/registration probes must not refresh session liveness."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from runtime.api.test_sessions import _p, _register
from yoke_core.domain.session_message_routing import session_liveness
from yoke_core.domain.session_reclaim_activity import latest_activity
from yoke_core.domain.sessions import SessionError, end_session, heartbeat

pytest_plugins = ("runtime.api.test_sessions",)

_STALE_AT = "2020-01-01T00:00:00Z"


def _backdate_heartbeat(conn, session_id: str, stamp: str = _STALE_AT) -> None:
    conn.execute(
        f"UPDATE harness_sessions SET last_heartbeat = {_p(conn)} "
        f"WHERE session_id = {_p(conn)}",
        (stamp, session_id),
    )
    conn.commit()


def _row(conn, session_id: str) -> dict:
    row = conn.execute(
        f"SELECT last_heartbeat, last_tool_call_at, ended_at "
        f"FROM harness_sessions WHERE session_id = {_p(conn)}",
        (session_id,),
    ).fetchone()
    assert row is not None
    return {
        "last_heartbeat": row["last_heartbeat"],
        "last_tool_call_at": row["last_tool_call_at"],
        "ended_at": row["ended_at"],
    }


class TestProbeDoesNotStampLiveness:
    def test_reactivation_preserves_last_heartbeat(self, conn) -> None:
        original = _register(conn, session_id="idle-wake")
        _backdate_heartbeat(conn, "idle-wake")
        before = _row(conn, "idle-wake")
        end_session(conn, "idle-wake")

        revived = _register(conn, session_id="idle-wake", model="new-model")
        after = _row(conn, "idle-wake")

        assert revived["ended_at"] is None
        assert after["last_heartbeat"] == before["last_heartbeat"]
        assert after["last_heartbeat"] != original["last_heartbeat"]
        assert after["last_heartbeat"] == _STALE_AT

    def test_live_reregister_preserves_last_heartbeat(self, conn) -> None:
        _register(conn, session_id="still-live")
        _backdate_heartbeat(conn, "still-live")
        before = _row(conn, "still-live")

        with pytest.raises(SessionError) as exc_info:
            _register(conn, session_id="still-live")
        assert exc_info.value.code == "SESSION_EXISTS"
        assert _row(conn, "still-live")["last_heartbeat"] == before["last_heartbeat"]

    def test_wake_reactivation_leaves_effective_liveness_age(self, conn) -> None:
        _register(conn, session_id="stale-idle")
        _backdate_heartbeat(conn, "stale-idle")
        age_before = latest_activity(conn, "stale-idle")
        now = datetime.now(timezone.utc)
        liveness_before = session_liveness(
            {
                "last_heartbeat": _STALE_AT,
                "last_tool_call_at": None,
                "executor": "claude-code",
            },
            now=now,
        )
        end_session(conn, "stale-idle")

        _register(conn, session_id="stale-idle")
        after = _row(conn, "stale-idle")
        age_after = latest_activity(conn, "stale-idle")
        liveness_after = session_liveness(
            {
                "last_heartbeat": after["last_heartbeat"],
                "last_tool_call_at": after["last_tool_call_at"],
                "executor": "claude-code",
            },
            now=now + timedelta(seconds=1),
        )

        assert age_after == age_before == _STALE_AT
        assert liveness_before == "stale"
        assert liveness_after == "stale"

    def test_explicit_heartbeat_still_stamps(self, conn) -> None:
        _register(conn, session_id="real-activity")
        _backdate_heartbeat(conn, "real-activity")
        result = heartbeat(conn, "real-activity")
        assert result["last_heartbeat"] > _STALE_AT
        assert latest_activity(conn, "real-activity") != _STALE_AT
