"""The ``sessions.list`` exact-session roster projection and its live probe.

The anchor-contention healer needs one positive answer — is this session
ended? — independent of the roster limit window. These tests cover the
complete ``session_id`` row end to end on the real test DB, and the
transport probe's mapping of that projection into live / ended / unknown.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    FunctionCallResponse,
    TargetRef,
)
from yoke_core.domain.handlers.sessions_list import handle_sessions_list
from yoke_core.domain.session_control_roster import SESSION_CONTROL_ROSTER_FIELDS
from yoke_core.domain.session_control_schema import create_session_control_tables

from runtime.api.domain.handlers.test_sessions_list_handler import (
    _insert_item_claim,
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
    @pytest.fixture(autouse=True)
    def _session_control_schema(self, test_db):
        create_session_control_tables(test_db)
        test_db.commit()

    def test_live_session_projects_the_complete_roster_row(self, test_db):
        from runtime.api.fixtures.backlog import insert_item

        insert_item(test_db, id=41, title="Fleet acceptance")
        test_db.commit()
        _insert_session(
            test_db,
            "s-live",
            last_heartbeat=_iso(),
            current_item_id="41",
        )
        test_db.execute(
            "UPDATE harness_sessions SET executor_surface=%s,executor_version=%s,"
            "machine_id=%s WHERE session_id=%s",
            ("claude-cli", "2.1.241", "machine-1", "s-live"),
        )
        test_db.commit()
        _insert_item_claim(test_db, "s-live", 41)
        outcome = handle_sessions_list(_request({"session_id": "s-live"}))
        result = outcome.result_payload
        assert result["fields"] == list(SESSION_CONTROL_ROSTER_FIELDS)
        (row,) = result["rows"]
        assert row["session_id"] == "s-live"
        assert row["liveness"] == "active"
        assert row["mode"] == "wait"
        assert row["ended_at"] is None
        assert row["claims"][0]["target"] == "YOK-41"
        assert row["current_item"] == "YOK-41"
        assert row["executor_surface"] == "claude-cli"
        assert row["executor_version"] == "2.1.241"
        assert row["machine_id"] == "machine-1"
        assert isinstance(row["messageability"], dict)

        roster = handle_sessions_list(_request({})).result_payload
        expected = next(
            candidate
            for candidate in roster["rows"]
            if candidate["session_id"] == "s-live"
        )
        assert row == expected

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

    def test_project_and_liveness_still_narrow_the_point_lookup(self, test_db):
        _insert_session(test_db, "s-live", last_heartbeat=_iso())
        test_db.execute(
            "INSERT INTO projects (id,slug,name,created_at) VALUES (%s,%s,%s,%s)",
            (77, "other", "Other", _iso()),
        )
        test_db.commit()

        wrong_liveness = handle_sessions_list(
            _request({"session_id": "s-live", "liveness": "ended"})
        )
        assert wrong_liveness.result_payload["rows"] == []
        wrong_project = handle_sessions_list(
            _request({"session_id": "s-live", "project": "other"})
        )
        assert wrong_project.result_payload["rows"] == []


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
            result={"fields": list(SESSION_CONTROL_ROSTER_FIELDS), "rows": rows},
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

    def test_no_row_positively_reads_as_not_a_live_session(self, monkeypatch):
        # Session rows are never deleted, so an id with no registration is
        # not a conversation on this control plane — the poisoning class.
        probe = self._probe_with(monkeypatch, self._response([]))
        assert probe("s") is False

    def test_probe_failure_maps_to_unknown(self, monkeypatch):
        probe = self._probe_with(monkeypatch, RuntimeError("transport down"))
        assert probe("s") is None
        assert probe("") is None

    def test_a_roster_answer_cannot_speak_for_the_probed_session(
        self, monkeypatch,
    ):
        """A server predating the filter returns the roster unfiltered.

        Only a row naming the probed id may answer for it: an unfiltered
        roster maps to unknown — never to another session's liveness —
        unless the probed session happens to be inside the returned window.
        """
        roster = [
            {"session_id": "someone-else", "liveness": "ended"},
            {"session_id": "another", "liveness": "active"},
        ]
        probe = self._probe_with(monkeypatch, self._response(roster))
        assert probe("s") is None

        probe = self._probe_with(
            monkeypatch,
            self._response(roster + [{"session_id": "s", "liveness": "ended"}]),
        )
        assert probe("s") is False
