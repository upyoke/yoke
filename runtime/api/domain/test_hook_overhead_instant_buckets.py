"""Hourly timing reports retain native clocks through their registered reader."""

import json
from datetime import timedelta

import pytest

from yoke_contracts.api.function_call import FunctionCallResponse
from yoke_contracts.timestamps import format_instant, parse_instant
from yoke_core.domain import hook_overhead, hook_overhead_tool
from yoke_core.domain.handlers.sessions_hook_overhead import (
    handle_sessions_hook_overhead,
)

NOW = parse_instant("1970-01-01T00:30:00.123456Z")
CUTOFF = NOW - timedelta(hours=1)
NEXT_HOUR = parse_instant("1970-01-01T00:00:00Z")


@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "Asia/Kathmandu"])
def test_native_hour_buckets_cutoff_and_wire_owner(test_db, monkeypatch, zone):
    from runtime.api.domain.handlers.test_sessions_hook_overhead import (
        _request,
        _use_fixture_database,
    )
    from runtime.api.fixtures.backlog import insert_event

    _use_fixture_database(monkeypatch, test_db)
    monkeypatch.setattr(hook_overhead, "utc_now", lambda: NOW)
    monkeypatch.setattr(hook_overhead_tool, "utc_now", lambda: NOW)
    test_db.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
    instants = [
        CUTOFF - timedelta(microseconds=1),
        CUTOFF,
        NEXT_HOUR - timedelta(microseconds=1),
        NEXT_HOUR,
    ]
    for index, instant in enumerate(instants):
        for kind, name in [
            ("hook_dispatch", "HookDispatchTelemetry"),
            ("tool_call", "HarnessToolCallCompleted"),
        ]:
            insert_event(
                test_db,
                event_id=f"{kind}-{index}",
                event_name=name,
                event_type=kind,
                source_type="hook",
                session_id=f"session-{index}",
                hook_event_name="PreToolUse" if kind == "hook_dispatch" else None,
                duration_ms=40,
                created_at=instant,
                envelope=json.dumps(
                    {"context": {"executor": "codex", "client_wall_ms": 60}}
                ),
            )
    assert test_db.execute("SHOW TimeZone").fetchone()[0] == zone
    outcome = handle_sessions_hook_overhead(_request(1))
    assert outcome.primary_success
    payload = outcome.result_payload
    for field, count in [("rows", "hook_count"), ("tool_rows", "call_count")]:
        rows = [row for row in payload[field] if row["scope"] == "global"]
        assert [row["hour_utc"] for row in rows] == [
            NEXT_HOUR,
            NEXT_HOUR - timedelta(hours=1),
        ]
        assert [row[count] for row in rows] == [1, 2]
        assert [row["tool_active_session_count"] for row in rows] == [1, 2]
    wire = FunctionCallResponse(
        function="sessions.hook_overhead", version="v1", success=True, result=payload
    ).model_dump(mode="json")["result"]
    for field in ("rows", "tool_rows"):
        assert [row["hour_utc"] for row in wire[field]] == [
            format_instant(row["hour_utc"]) for row in payload[field]
        ]
        assert {row["hour_utc"] for row in wire[field]} == {
            "1970-01-01T00:00:00.000000Z",
            "1969-12-31T23:00:00.000000Z",
        }
        assert all(row["harness"] in {"all", "codex"} for row in wire[field])
