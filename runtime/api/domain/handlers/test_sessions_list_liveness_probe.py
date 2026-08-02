"""The ``sessions.list`` single-session projection and the probe over it.

The anchor-contention healer needs one positive answer — is this session
ended? — independent of the roster limit window. These tests cover the
``session_id`` payload filter end to end on the real test DB, and the
transport probe's mapping of that projection into live / ended / unknown.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    FunctionCallResponse,
    TargetRef,
)
from yoke_core.domain.handlers.sessions_list import (
    SESSION_LIVENESS_FIELDS,
    handle_sessions_list,
)

from runtime.api.domain.handlers.test_sessions_list_handler import (
    _insert_session,
)


def _iso(minutes_ago: int = 0) -> str:
    stamp = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return stamp.strftime("%Y-%m-%dT%H:%M:%SZ")


_LONG_AGO_MINUTES = 60 * 24 * 30


def _request(payload: dict) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="sessions.list",
        actor=ActorContext(actor_id=None, session_id=""),
        target=TargetRef(kind="global"),
        payload=payload,
    )


class TestSessionIdFilter:
    def test_live_session_projects_active(self, test_db):
        _insert_session(test_db, "s-live", last_heartbeat=_iso())
        outcome = handle_sessions_list(_request({"session_id": "s-live"}))
        result = outcome.result_payload
        assert result["fields"] == list(SESSION_LIVENESS_FIELDS)
        (row,) = result["rows"]
        assert row["session_id"] == "s-live"
        assert row["liveness"] == "active"
        assert row["ended_at"] == ""

    def test_quiet_session_projects_stale_not_ended(self, test_db):
        _insert_session(
            test_db, "s-quiet", last_heartbeat=_iso(_LONG_AGO_MINUTES),
        )
        outcome = handle_sessions_list(_request({"session_id": "s-quiet"}))
        (row,) = outcome.result_payload["rows"]
        assert row["liveness"] == "stale"

    def test_ended_session_projects_ended(self, test_db):
        _insert_session(
            test_db, "s-done",
            last_heartbeat=_iso(_LONG_AGO_MINUTES),
            ended_at=_iso(5),
        )
        outcome = handle_sessions_list(_request({"session_id": "s-done"}))
        (row,) = outcome.result_payload["rows"]
        assert row["liveness"] == "ended"
        assert row["ended_at"]

    def test_unregistered_session_returns_no_rows(self, test_db):
        outcome = handle_sessions_list(_request({"session_id": "s-none"}))
        assert outcome.result_payload["rows"] == []

    def test_blank_filter_is_a_payload_error(self, test_db):
        outcome = handle_sessions_list(_request({"session_id": "  "}))
        assert outcome.primary_success is False
        assert outcome.error.code == "payload_invalid"

    def test_filter_bypasses_the_roster_limit_window(self, test_db):
        for index in range(5):
            _insert_session(
                test_db, f"s-noise-{index}", last_heartbeat=_iso(),
            )
        _insert_session(
            test_db, "s-target", last_heartbeat=_iso(_LONG_AGO_MINUTES),
        )
        outcome = handle_sessions_list(
            _request({"session_id": "s-target", "limit": 1}),
        )
        (row,) = outcome.result_payload["rows"]
        assert row["session_id"] == "s-target"


class TestContenderIsLiveProbe:
    def _probe_with(self, monkeypatch, response):
        from yoke_cli.transport import dispatcher as transport
        from yoke_cli.transport.session_liveness import contender_is_live

        def fake(**kwargs):
            if isinstance(response, Exception):
                raise response
            return response

        monkeypatch.setattr(transport, "call_dispatcher", fake)
        return contender_is_live

    def _response(self, rows):
        return FunctionCallResponse(
            success=True, function="sessions.list", version="v1",
            result={"fields": list(SESSION_LIVENESS_FIELDS), "rows": rows},
        )

    def test_stale_maps_to_live(self, monkeypatch):
        probe = self._probe_with(
            monkeypatch,
            self._response([{"session_id": "s", "liveness": "stale"}]),
        )
        assert probe("s") is True

    def test_ended_maps_to_ended(self, monkeypatch):
        probe = self._probe_with(
            monkeypatch,
            self._response([{"session_id": "s", "liveness": "ended"}]),
        )
        assert probe("s") is False

    def test_no_row_and_failure_map_to_unknown(self, monkeypatch):
        probe = self._probe_with(monkeypatch, self._response([]))
        assert probe("s") is None
        probe = self._probe_with(monkeypatch, RuntimeError("transport down"))
        assert probe("s") is None
        assert probe("") is None
