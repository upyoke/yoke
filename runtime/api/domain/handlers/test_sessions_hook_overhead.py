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


def _dispatch_envelope(
    timing_id: str,
    duration_ms: int | None,
    *,
    executor: str = "cursor",
    client_wall_ms: int | None = None,
) -> str:
    context = {
        "hook_wait_ms": duration_ms,
        "client_timing_id": timing_id,
        "executor": executor,
    }
    if client_wall_ms is not None:
        context["client_wall_ms"] = client_wall_ms
    return json.dumps(
        {
            "event_name": "HookDispatchTelemetry",
            "duration_ms": duration_ms,
            "context": context,
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
    monkeypatch.setattr(hook_overhead, "tool_latency_rows", lambda hours: [])
    accepted = sessions_hook_overhead.handle_sessions_hook_overhead(_request(12))
    assert accepted.primary_success is True
    assert accepted.result_payload == {
        "fields": hook_overhead.HOOK_OVERHEAD_FIELDS,
        "rows": [],
        "tool_fields": hook_overhead.TOOL_LATENCY_FIELDS,
        "tool_rows": [],
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
        envelope = _dispatch_envelope(event_id, server_ms, client_wall_ms=client_ms)
        insert_event(
            test_db,
            event_id=event_id,
            event_name="HookDispatchTelemetry",
            event_type="hook_dispatch",
            source_type="hook",
            duration_ms=server_ms,
            hook_event_name=hook_event,
            envelope=envelope,
        )

    rows = hook_overhead.hook_overhead_rows(1)
    assert len(rows) == 2
    row = next(row for row in rows if row["scope"] == "global")
    assert row["hook_count"] == 4
    assert row["evaluator_timed_count"] == 4
    assert row["evaluator_timing_coverage_pct"] == 100.0
    assert row["client_timed_count"] == 4
    assert row["client_timing_coverage_pct"] == 100.0
    assert row["comparison_status"] == "comparable"
    assert row["pre_client_p50_ms"] == 120
    assert row["pre_client_mean_ms"] == 120
    assert row["pre_evaluator_p50_ms"] == 50
    assert row["pre_remainder_p50_ms"] == 70
    assert row["post_client_p50_ms"] == 80
    assert row["post_client_mean_ms"] == 80
    assert row["post_evaluator_p50_ms"] == 40
    assert row["post_remainder_p50_ms"] == 40
    assert row["overhead_per_tool_call_ms"] == 200


def test_missing_durations_are_coverage_gaps_while_zero_is_timed(
    test_db, monkeypatch
) -> None:
    _use_fixture_database(monkeypatch, test_db)
    samples = [
        ("zero", "PreToolUse", 0, 0),
        ("missing-server", "PreToolUse", None, 25),
        ("missing-client", "PostToolUse", 30, None),
    ]
    for event_id, hook_event, server_ms, client_ms in samples:
        insert_event(
            test_db,
            event_id=event_id,
            event_name="HookDispatchTelemetry",
            event_type="hook_dispatch",
            source_type="hook",
            duration_ms=server_ms,
            hook_event_name=hook_event,
            session_id=f"session-{event_id}",
            envelope=_dispatch_envelope(event_id, server_ms, client_wall_ms=client_ms),
        )

    row = next(
        row for row in hook_overhead.hook_overhead_rows(1) if row["scope"] == "global"
    )
    assert row["evaluator_timed_count"] == 2
    assert row["evaluator_timing_coverage_pct"] == 66.7
    assert row["client_timed_count"] == 2
    assert row["client_timing_coverage_pct"] == 66.7
    assert row["pre_evaluator_p50_ms"] == 0
    assert row["pre_client_p50_ms"] == 12
    assert row["comparison_status"] == "incomplete"
    assert row["tool_active_session_count"] == 3


def test_tool_latency_reports_timed_total_globally_and_per_harness(
    test_db, monkeypatch
) -> None:
    _use_fixture_database(monkeypatch, test_db)
    samples = [
        ("cursor-zero", "cursor", 0),
        ("cursor-missing", "cursor", None),
        ("codex-timed", "codex", 120),
    ]
    for event_id, executor, duration_ms in samples:
        insert_event(
            test_db,
            event_id=event_id,
            event_name="HarnessToolCallCompleted",
            event_type="tool_call",
            source_type="hook",
            duration_ms=duration_ms,
            session_id=f"session-{event_id}",
            envelope=json.dumps({"context": {"executor": executor}}),
        )

    rows = hook_overhead.tool_latency_rows(1)
    global_row = next(row for row in rows if row["scope"] == "global")
    cursor_row = next(
        row for row in rows if row["scope"] == "harness" and row["harness"] == "cursor"
    )
    codex_row = next(
        row for row in rows if row["scope"] == "harness" and row["harness"] == "codex"
    )

    assert global_row["timed_count"] == 2
    assert global_row["call_count"] == 3
    assert global_row["timing_coverage_pct"] == 66.7
    assert global_row["mean_ms"] == 60
    assert global_row["comparison_status"] == "incomplete"
    assert cursor_row["timed_count"] == 1
    assert cursor_row["call_count"] == 2
    assert cursor_row["mean_ms"] == 0
    assert cursor_row["unsupported_count"] == 0
    assert cursor_row["unknown_count"] == 1
    assert cursor_row["unsupported_timing_reason"] == ""
    assert codex_row["timing_coverage_pct"] == 100.0
    assert codex_row["comparison_status"] == "comparable"
    assert codex_row["unsupported_count"] == 0
    assert codex_row["unknown_count"] == 0


def test_cursor_shell_missing_duration_is_unsupported_not_unknown(
    test_db, monkeypatch
) -> None:
    from yoke_contracts.cursor_shell_timing import (
        CURSOR_SHELL_TIMING_UNSUPPORTED_REASON,
    )

    _use_fixture_database(monkeypatch, test_db)
    insert_event(
        test_db,
        event_id="cursor-shell",
        event_name="HarnessToolCallCompleted",
        event_type="tool_call",
        source_type="hook",
        duration_ms=None,
        tool_name="Bash",
        session_id="session-cursor-shell",
        envelope=json.dumps({"context": {"executor": "cursor"}}),
    )
    insert_event(
        test_db,
        event_id="claude-bash",
        event_name="HarnessToolCallCompleted",
        event_type="tool_call",
        source_type="hook",
        duration_ms=80,
        tool_name="Bash",
        tool_use_id="tu-claude",
        session_id="session-claude-bash",
        envelope=json.dumps({"context": {"executor": "claude-code"}}),
    )

    rows = hook_overhead.tool_latency_rows(1)
    cursor_row = next(
        row for row in rows if row["scope"] == "harness" and row["harness"] == "cursor"
    )
    claude_row = next(
        row
        for row in rows
        if row["scope"] == "harness" and row["harness"] == "claude-code"
    )
    assert cursor_row["timed_count"] == 0
    assert cursor_row["unsupported_count"] == 1
    assert cursor_row["unknown_count"] == 0
    assert cursor_row["comparison_status"] == "unsupported"
    assert cursor_row["unsupported_timing_reason"] == (
        CURSOR_SHELL_TIMING_UNSUPPORTED_REASON
    )
    assert claude_row["timed_count"] == 1
    assert claude_row["unsupported_count"] == 0
    assert claude_row["comparison_status"] == "comparable"
