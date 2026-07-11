"""Handler coverage for the events.* read family (disposable Postgres)."""

from __future__ import annotations

from yoke_core.domain.handlers import events_reads
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from runtime.api.conftest import insert_event


def _request(function_id: str, payload=None, target=None) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function_id,
        actor=ActorContext(actor_id="op", session_id="s-caller"),
        target=target or TargetRef(kind="global"),
        payload=payload or {},
    )


class TestEventsQuery:
    def test_filter_schema_omits_platform_user_identity(self):
        properties = events_reads.EventsFilterRequest.model_json_schema()["properties"]
        assert "user_id" not in properties

    def test_rejects_bad_limit(self):
        outcome = events_reads.handle_events_query(
            _request("events.query.run", {"limit": 5000})
        )
        assert not outcome.primary_success
        assert outcome.error.code == "payload_invalid"

    def test_rejects_unparseable_since(self):
        outcome = events_reads.handle_events_query(
            _request("events.query.run", {"since": "not-a-time"})
        )
        assert not outcome.primary_success
        assert outcome.error.code == "payload_invalid"
        assert "since" in outcome.error.message

    def test_current_episode_requires_session_filter(self):
        outcome = events_reads.handle_events_query(
            _request("events.query.run", {"current_episode": True})
        )
        assert not outcome.primary_success
        assert outcome.error.code == "payload_invalid"
        assert "session-id" in outcome.error.message

    def test_current_episode_fails_closed_without_boundary(self, test_db):
        insert_event(
            test_db, event_id="evt-1", event_name="SomethingHappened",
            session_id="s-epi",
        )
        test_db.commit()
        outcome = events_reads.handle_events_query(
            _request(
                "events.query.run",
                {"session_id": "s-epi", "current_episode": True},
            )
        )
        assert outcome.primary_success
        assert outcome.result_payload["rows"] == []

    def test_current_episode_returns_rows_after_boundary(self, test_db):
        insert_event(
            test_db, event_id="evt-old", event_name="BeforeBoundary",
            session_id="s-epi", created_at="2026-01-01T00:00:00Z",
        )
        insert_event(
            test_db, event_id="evt-boundary",
            event_name="HarnessSessionStarted",
            session_id="s-epi", created_at="2026-01-02T00:00:00Z",
        )
        insert_event(
            test_db, event_id="evt-new", event_name="AfterBoundary",
            session_id="s-epi", created_at="2026-01-03T00:00:00Z",
        )
        # Boundary truth is harness_sessions.episode_started_at (stamped
        # by register_session); the rows above are telemetry being filtered.
        test_db.execute(
            "INSERT INTO harness_sessions (session_id, executor, provider, "
            "model, workspace, offered_at, last_heartbeat, episode_started_at) "
            "VALUES ('s-epi', 'claude-code', 'anthropic', 'm', '/tmp', "
            "'2026-01-02T00:00:00Z', '2026-01-02T00:00:00Z', "
            "'2026-01-02T00:00:00Z')"
        )
        test_db.commit()
        outcome = events_reads.handle_events_query(
            _request(
                "events.query.run",
                {"session_id": "s-epi", "current_episode": True},
            )
        )
        assert outcome.primary_success
        names = [r["event_name"] for r in outcome.result_payload["rows"]]
        assert "AfterBoundary" in names
        assert "BeforeBoundary" not in names

    def test_filters_by_event_name_with_full_projection(self, test_db):
        insert_event(
            test_db, event_id="evt-a", event_name="EventA",
            envelope='{"k":1}', anomaly_flags="nonzero_exit",
        )
        insert_event(test_db, event_id="evt-b", event_name="EventB")
        test_db.commit()
        outcome = events_reads.handle_events_query(
            _request("events.query.run", {"event_name": "EventA"})
        )
        assert outcome.primary_success
        rows = outcome.result_payload["rows"]
        assert len(rows) == 1
        row = rows[0]
        assert row["event_name"] == "EventA"
        assert row["envelope"] == '{"k":1}'
        assert row["anomaly_flags"] == "nonzero_exit"
        # Full 24-column projection + envelope.
        from yoke_core.domain.events_crud import EVT_COLUMN_NAMES

        assert set(row.keys()) == {*EVT_COLUMN_NAMES, "envelope"}

    def test_item_filter_rides_resolved_target(self, test_db):
        insert_event(
            test_db, event_id="evt-i", event_name="ItemEvent", item_id="42",
        )
        insert_event(test_db, event_id="evt-g", event_name="GlobalEvent")
        test_db.commit()
        outcome = events_reads.handle_events_query(
            _request(
                "events.query.run", {},
                target=TargetRef(kind="item", item_id=42),
            )
        )
        assert outcome.primary_success
        names = [r["event_name"] for r in outcome.result_payload["rows"]]
        assert names == ["ItemEvent"]


class TestEventsTail:
    def test_returns_newest_first_with_limit(self, test_db):
        for n in range(3):
            insert_event(
                test_db, event_id=f"evt-{n}", event_name=f"Event{n}",
                created_at=f"2026-01-0{n + 1}T00:00:00Z",
            )
        test_db.commit()
        outcome = events_reads.handle_events_tail(
            _request("events.tail.run", {"limit": 2})
        )
        assert outcome.primary_success
        names = [r["event_name"] for r in outcome.result_payload["rows"]]
        assert names == ["Event2", "Event1"]

    def test_rejects_bad_limit(self):
        outcome = events_reads.handle_events_tail(
            _request("events.tail.run", {"limit": 0})
        )
        assert not outcome.primary_success
        assert outcome.error.code == "payload_invalid"


class TestEventsCount:
    def test_counts_with_filters(self, test_db):
        insert_event(test_db, event_id="evt-1", event_name="CountMe")
        insert_event(test_db, event_id="evt-2", event_name="CountMe")
        insert_event(test_db, event_id="evt-3", event_name="NotMe")
        test_db.commit()
        outcome = events_reads.handle_events_count(
            _request("events.count.run", {"event_name": "CountMe"})
        )
        assert outcome.primary_success
        assert outcome.result_payload["count"] == 2


class TestEventsAnomalies:
    def test_returns_only_flagged_rows(self, test_db):
        insert_event(
            test_db, event_id="evt-anom", event_name="Anomalous",
            anomaly_flags="nonzero_exit",
        )
        insert_event(test_db, event_id="evt-clean", event_name="Clean")
        test_db.commit()
        outcome = events_reads.handle_events_anomalies(
            _request("events.anomalies.run", {})
        )
        assert outcome.primary_success
        names = [r["event_name"] for r in outcome.result_payload["rows"]]
        assert names == ["Anomalous"]
