"""Coverage for client-wall completion and hourly hook overhead reads."""

from __future__ import annotations

import json

from runtime.api.fixtures.backlog import insert_event
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain import hook_client_wall, hook_overhead
from yoke_core.domain.handlers import sessions_hook_overhead


class _KeepOpenConnection:
    def __init__(self, connection) -> None:
        self.connection = connection

    def __getattr__(self, name):
        return getattr(self.connection, name)

    def close(self) -> None:
        pass


def _use_fixture_database(monkeypatch, test_db) -> None:
    connection = _KeepOpenConnection(test_db)
    monkeypatch.setattr(hook_client_wall.db_backend, "connect", lambda: connection)
    monkeypatch.setattr(hook_overhead.db_backend, "connect", lambda: connection)
    monkeypatch.setattr(
        hook_client_wall.db_backend, "connection_is_postgres", lambda _conn: True
    )


def _dispatch_envelope(timing_id: str, duration_ms: int) -> str:
    return json.dumps(
        {
            "event_name": "HookDispatchTelemetry",
            "duration_ms": duration_ms,
            "context": {
                "hook_wait_ms": duration_ms,
                "client_timing_id": timing_id,
            },
        }
    )


def _request(hours) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="sessions.hook_overhead",
        actor=ActorContext(session_id="hook-overhead-test"),
        target=TargetRef(kind="global"),
        payload={"hours": hours},
    )


def test_handler_validates_the_hour_window_and_returns_registered_shape(
    monkeypatch,
) -> None:
    monkeypatch.setattr(hook_overhead, "hook_overhead_rows", lambda hours: [])
    accepted = sessions_hook_overhead.handle_sessions_hook_overhead(_request(12))
    assert accepted.primary_success is True
    assert accepted.result_payload == {
        "fields": hook_overhead.HOOK_OVERHEAD_FIELDS,
        "rows": [],
    }

    refused = sessions_hook_overhead.handle_sessions_hook_overhead(_request(0))
    assert refused.primary_success is False
    assert refused.error.code == "payload_invalid"


def test_evaluated_hook_client_wall_is_never_shorter_than_server_duration(
    test_db, monkeypatch
) -> None:
    _use_fixture_database(monkeypatch, test_db)
    timing_id = "38bfc729-0b61-45e1-8821-fe570de54aa5"
    insert_event(
        test_db,
        event_id="dispatch-invariant",
        event_name="HookDispatchTelemetry",
        event_type="hook_dispatch",
        source_type="hook",
        duration_ms=83,
        hook_event_name="PreToolUse",
        client_timing_id=timing_id,
        envelope=_dispatch_envelope(timing_id, 83),
    )

    assert hook_client_wall.record_client_wall_reports([(timing_id, 21)]) == 1
    row = test_db.execute(
        "SELECT duration_ms, envelope FROM events WHERE event_id=%s",
        ("dispatch-invariant",),
    ).fetchone()
    context = json.loads(row[1])["context"]
    assert context["client_wall_ms"] >= row[0]


def test_hourly_projection_splits_client_server_and_remainder(
    test_db, monkeypatch
) -> None:
    _use_fixture_database(monkeypatch, test_db)
    samples = [
        ("pre-a", "PreToolUse", 40, 100),
        ("pre-b", "PreToolUse", 60, 140),
        ("post-a", "PostToolUse", 30, 70),
        ("post-b", "PostToolUse", 50, 90),
    ]
    for event_id, hook_event, server_ms, client_ms in samples:
        envelope = json.loads(_dispatch_envelope(event_id, server_ms))
        envelope["context"]["client_wall_ms"] = client_ms
        insert_event(
            test_db,
            event_id=event_id,
            event_name="HookDispatchTelemetry",
            event_type="hook_dispatch",
            source_type="hook",
            duration_ms=server_ms,
            hook_event_name=hook_event,
            envelope=json.dumps(envelope),
        )

    rows = hook_overhead.hook_overhead_rows(1)
    assert len(rows) == 1
    row = rows[0]
    assert row["hook_count"] == 4
    assert row["pre_client_p50_ms"] == 120
    assert row["pre_server_p50_ms"] == 50
    assert row["pre_remainder_p50_ms"] == 70
    assert row["post_client_p50_ms"] == 80
    assert row["post_server_p50_ms"] == 40
    assert row["post_remainder_p50_ms"] == 40
    assert row["overhead_per_tool_call_ms"] == 200
