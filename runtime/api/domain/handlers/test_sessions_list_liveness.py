"""Derived session liveness and the ended-cause facet.

Liveness has four states (the parked-holder ``waiting`` state has its own
file); how an ended session got there is a separate
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
from runtime.api.steering_fleet_test_helpers import (
    seed_delivery_attempt,
    seed_message,
)
from yoke_core.domain.sessions_list_read import ENDED_CAUSES, list_sessions


#: An ended session in this file offered itself well before it ended, so
#: it reads as a session that did work rather than as a harness startup
#: probe (:mod:`yoke_core.domain.session_probe`), which is never listed.
_WORKED_A_WHILE_MINUTES = 60 * 24 * 31


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
            offered_at=_iso(_WORKED_A_WHILE_MINUTES),
            last_heartbeat=_iso(_LONG_AGO_MINUTES),
            ended_at=_iso(_LONG_AGO_MINUTES),
        )
        _insert_session(
            test_db,
            "s-killed",
            offered_at=_iso(_WORKED_A_WHILE_MINUTES),
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
        assert rows[0]["last_tool_call_at"] == recent_tool_call

    def test_process_gone_evidence_is_current_only_until_later_activity(self, test_db):
        old = _iso(_LONG_AGO_MINUTES)
        observed = _iso()
        _insert_session(test_db, "s-gone", last_heartbeat=old)
        test_db.execute(
            "UPDATE harness_sessions SET native_process_gone_at=%s, "
            "native_process_gone_evidence=%s WHERE session_id=%s",
            (observed, '{"pids":[42]}', "s-gone"),
        )
        test_db.commit()

        row = list_sessions()[0]
        assert row["native_process"] == {
            "state": "gone",
            "observed_at": observed,
            "evidence": {"pids": [42]},
            "resumable_from_transcript": False,
        }

        test_db.execute(
            "UPDATE harness_sessions SET last_heartbeat=%s WHERE session_id=%s",
            (_iso(-1), "s-gone"),
        )
        test_db.commit()
        assert list_sessions()[0]["native_process"] is None

    def test_a_wake_answering_the_exit_projects_resuming(self, test_db):
        exited = _iso(10)
        woken = _iso(1)
        _insert_session(test_db, "s-resuming", last_heartbeat=_iso(_LONG_AGO_MINUTES))
        test_db.execute(
            "UPDATE harness_sessions SET native_process_gone_at=%s, "
            "native_process_gone_evidence='{}' WHERE session_id='s-resuming'",
            (exited,),
        )
        seed_message(
            test_db, "m-resume", sender="s-resuming", to="s-resuming", at=woken
        )
        seed_delivery_attempt(
            test_db,
            "wake-resume",
            message_id="m-resume",
            to="s-resuming",
            result_code="wake_delivered",
            started_at=woken,
        )
        test_db.commit()

        assert list_sessions()[0]["native_process"] == {
            "state": "resuming",
            "observed_at": exited,
            "resume_started_at": woken,
            "resume_attempt_id": "wake-resume",
        }

    def test_liveness_filter_and_rejection(self, test_db):
        _insert_session(test_db, "s-active", last_heartbeat=_iso())
        _insert_session(
            test_db,
            "s-ended",
            offered_at=_iso(_WORKED_A_WHILE_MINUTES),
            last_heartbeat=_iso(_LONG_AGO_MINUTES),
            ended_at=_iso(_LONG_AGO_MINUTES),
        )
        _insert_session(
            test_db,
            "s-killed",
            offered_at=_iso(_WORKED_A_WHILE_MINUTES),
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
