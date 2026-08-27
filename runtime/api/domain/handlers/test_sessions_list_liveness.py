"""Derived session liveness and the ended-cause facet.

Liveness has three states; how an ended session got there is a separate
facet, so a killed session reads ``ended`` with ``ended_cause='killed'``
rather than as a liveness value of its own.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from runtime.api.domain.handlers.test_sessions_list_handler import (
    _LONG_AGO_MINUTES,
    _insert_session,
)
from yoke_core.domain.sessions_list_read import ENDED_CAUSES, list_sessions


def _iso(minutes_ago: int = 0) -> str:
    stamp = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return stamp.strftime("%Y-%m-%dT%H:%M:%SZ")


class TestLivenessDerivation:
    def test_active_stale_and_ended_states_with_the_ended_cause(self, test_db):
        # A kill is ended like any other gone session; ended_cause carries it.
        _insert_session(test_db, "s-active", last_heartbeat=_iso())
        _insert_session(test_db, "s-stale", last_heartbeat=_iso(_LONG_AGO_MINUTES))
        _insert_session(
            test_db,
            "s-ended",
            last_heartbeat=_iso(_LONG_AGO_MINUTES),
            ended_at=_iso(_LONG_AGO_MINUTES),
        )
        _insert_session(
            test_db,
            "s-killed",
            last_heartbeat=_iso(_LONG_AGO_MINUTES),
            ended_at=_iso(_LONG_AGO_MINUTES),
            terminated_at=_iso(_LONG_AGO_MINUTES),
        )

        by_id = {row["session_id"]: row for row in list_sessions()}
        assert by_id["s-active"]["liveness"] == "active"
        assert by_id["s-active"]["ended_cause"] is None
        assert by_id["s-stale"]["liveness"] == "stale"
        assert by_id["s-ended"]["liveness"] == "ended"
        assert by_id["s-ended"]["ended_cause"] == "wound_down"
        assert by_id["s-killed"]["liveness"] == "ended"
        assert by_id["s-killed"]["ended_cause"] == "killed"

    def test_recent_tool_call_keeps_an_old_heartbeat_session_active(self, test_db):
        # Tool activity keeps the session live even with an old heartbeat.
        recent_tool_call = _iso()
        _insert_session(
            test_db,
            "s-tooling",
            last_heartbeat=_iso(_LONG_AGO_MINUTES),
            last_tool_call_at=recent_tool_call,
        )
        rows = list_sessions()
        assert rows[0]["session_id"] == "s-tooling"
        assert rows[0]["liveness"] == "active"
        assert rows[0]["activity_at"] == recent_tool_call

    def test_liveness_filter_and_rejection(self, test_db):
        _insert_session(test_db, "s-active", last_heartbeat=_iso())
        _insert_session(
            test_db,
            "s-ended",
            last_heartbeat=_iso(_LONG_AGO_MINUTES),
            ended_at=_iso(_LONG_AGO_MINUTES),
        )
        _insert_session(
            test_db,
            "s-killed",
            last_heartbeat=_iso(_LONG_AGO_MINUTES),
            ended_at=_iso(_LONG_AGO_MINUTES),
            terminated_at=_iso(_LONG_AGO_MINUTES),
        )
        active_only = list_sessions(liveness="active")
        assert [row["session_id"] for row in active_only] == ["s-active"]
        ended_only = list_sessions(liveness="ended")
        assert sorted(row["session_id"] for row in ended_only) == [
            "s-ended",
            "s-killed",
        ]
        killed_only = list_sessions(ended_cause="killed")
        assert [row["session_id"] for row in killed_only] == ["s-killed"]
        wound_down_only = list_sessions(ended_cause="wound_down")
        assert [row["session_id"] for row in wound_down_only] == ["s-ended"]
        for bad in ("running", "terminated"):
            with pytest.raises(ValueError):
                list_sessions(liveness=bad)
        with pytest.raises(ValueError):
            list_sessions(ended_cause="stopped")
        with pytest.raises(ValueError, match="--liveness ended"):
            list_sessions(liveness="active", ended_cause="killed")
        assert ENDED_CAUSES == ("killed", "wound_down")
