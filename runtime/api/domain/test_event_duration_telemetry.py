"""Database-backed coverage for event duration telemetry."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import BaseModel

from runtime.api.fixtures.pg_testdb import test_database
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    HandlerOutcome,
    TargetRef,
)
from yoke_core.domain import observe_parsing
from yoke_core.domain import yoke_function_dispatch as dispatch_module
from yoke_core.domain import yoke_function_dispatch_events as events_module
from yoke_core.domain import (
    yoke_function_dispatch_observability as observability_module,
)
from yoke_core.domain.events import emit_event as native_emit_event
from yoke_core.domain.observe_event_emission import build_envelope, insert_event
from yoke_core.domain.yoke_function_dispatch import dispatch
from yoke_core.domain.yoke_function_registry import (
    register,
    reset_registry_for_tests,
)


class _RequestModel(BaseModel):
    pass


class _ResponseModel(BaseModel):
    pass


class _ManualClock:
    def __init__(self) -> None:
        self.current = 0.0

    def read(self) -> float:
        return self.current

    def advance(self, milliseconds: int) -> None:
        self.current += milliseconds / 1000


def _registry_kwargs() -> dict:
    return {
        "stability": "stable",
        "owner_module": "yoke_core.domain.yoke_function_dispatch",
        "target_kinds": ["item"],
        "side_effects": [],
        "emitted_event_names": ["YokeFunctionCalled"],
        "guardrails": [],
        "adapter_status": "live",
    }


def _request(function_id: str) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function_id,
        actor=ActorContext(actor_id="2", session_id="duration-session"),
        target=TargetRef(kind="item", item_id=42),
    )


def _timed_handler(clock: _ManualClock, milliseconds: int):
    def handler(_request):
        clock.advance(milliseconds)
        return HandlerOutcome(
            result_payload={"status": "ok"}, primary_success=True,
        )

    return handler


@pytest.fixture
def dispatch_db(monkeypatch):
    reset_registry_for_tests()
    monkeypatch.setattr(dispatch_module, "_HANDLERS_REGISTERED", True)
    monkeypatch.setattr(
        dispatch_module, "_idempotency_lookup", lambda *_args, **_kwargs: None,
    )
    try:
        with test_database() as conn:
            monkeypatch.setattr(
                events_module,
                "emit_event",
                lambda *args, **kwargs: native_emit_event(
                    *args, conn=conn, **kwargs,
                ),
            )
            yield conn
    finally:
        reset_registry_for_tests()


def test_dispatcher_persists_handler_duration_and_slow_call_is_larger(
    dispatch_db, monkeypatch,
) -> None:
    clock = _ManualClock()
    monkeypatch.setattr(observability_module, "_read_monotonic", clock.read)
    register(
        "duration.telemetry.fast",
        _timed_handler(clock, 5),
        _RequestModel,
        _ResponseModel,
        **_registry_kwargs(),
    )
    register(
        "duration.telemetry.slow",
        _timed_handler(clock, 125),
        _RequestModel,
        _ResponseModel,
        **_registry_kwargs(),
    )

    assert dispatch(_request("duration.telemetry.fast")).success is True
    assert dispatch(_request("duration.telemetry.slow")).success is True

    rows = dispatch_db.execute(
        "SELECT duration_ms, envelope FROM events "
        "WHERE event_name = 'YokeFunctionCalled' ORDER BY id"
    ).fetchall()
    durations = [int(row[0]) for row in rows]
    assert durations[0] >= 1
    assert durations[1] >= durations[0] * 10
    for row in rows:
        envelope = json.loads(row[1])
        assert envelope["duration_ms"] == row[0]
        assert envelope["context"]["duration_ms"] == row[0]


def test_dispatcher_keeps_running_when_duration_is_unavailable(
    dispatch_db, monkeypatch,
) -> None:
    monkeypatch.setattr(observability_module, "_read_monotonic", lambda: None)
    register(
        "duration.telemetry.unavailable",
        _timed_handler(_ManualClock(), 1),
        _RequestModel,
        _ResponseModel,
        **_registry_kwargs(),
    )

    response = dispatch(_request("duration.telemetry.unavailable"))

    assert response.success is True
    row = dispatch_db.execute(
        "SELECT duration_ms, envelope FROM events "
        "WHERE event_name = 'YokeFunctionCalled' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert row[0] is None
    assert json.loads(row[1])["duration_ms"] is None


def test_duration_clock_failure_degrades_to_none(monkeypatch) -> None:
    def fail_clock_read() -> float:
        raise RuntimeError("clock unavailable")

    monkeypatch.setattr(
        observability_module, "_read_monotonic", fail_clock_read,
    )

    assert observability_module.start_duration_measurement() is None


def test_post_tool_duration_uses_connected_authority_without_db_token() -> None:
    with test_database() as conn:
        started_at = datetime.now(timezone.utc) - timedelta(milliseconds=80)
        started_text = started_at.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        conn.execute(
            "INSERT INTO session_tool_calls "
            "(session_id, tool_use_id, tool_name, started_at) "
            "VALUES (%s, %s, %s, %s)",
            ("duration-session", "tool-duration", "Bash", started_text),
        )
        conn.commit()

        record = observe_parsing.parse_hook_event(
            {
                "tool_name": "Bash",
                "tool_input": {"command": "true"},
                "tool_response": {"content": "Exit code 0"},
            },
            session_id="duration-session",
            hook_event="PostToolUse",
            tool_use_id="tool-duration",
            db_path=None,
        )

        assert record is not None
        assert record.duration_ms is not None
        assert 50 <= record.duration_ms < 10_000
        insert_event(conn, build_envelope(record))
        row = conn.execute(
            "SELECT duration_ms, envelope FROM events "
            "WHERE event_name = 'HarnessToolCallCompleted' "
            "ORDER BY id DESC LIMIT 1"
        ).fetchone()
        assert row[0] == record.duration_ms
        assert json.loads(row[1])["duration_ms"] == record.duration_ms
