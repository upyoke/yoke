"""Hook-overhead reports read repaired owner timestamps, not ingest snapshots."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from runtime.api.domain.handlers.test_sessions_hook_overhead import (
    _use_fixture_database,
)
from runtime.api.fixtures.backlog import insert_event
from yoke_core.domain import hook_overhead
from yoke_core.domain.observe_timing import TIMING_PENDING_START_DELIVERY
from yoke_core.domain.session_activity_state import record_tool_call_started


def _stamp(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _insert_completion(
    conn,
    *,
    event_id: str,
    session_id: str,
    tool_use_id: str | None,
    executor: str,
    created_at: str,
    duration_ms: int | None = None,
    tool_name: str = "Read",
) -> None:
    insert_event(
        conn,
        event_id=event_id,
        event_name="HarnessToolCallCompleted",
        event_type="tool_call",
        source_type="hook",
        duration_ms=duration_ms,
        tool_name=tool_name,
        tool_use_id=tool_use_id,
        session_id=session_id,
        created_at=created_at,
        envelope=json.dumps({"context": {"executor": executor}}),
    )


def _open_closed_call(
    conn,
    *,
    session_id: str,
    tool_use_id: str,
    completed_at: datetime,
    started_at: datetime | None = None,
    tool_name: str = "Read",
) -> None:
    conn.execute(
        "INSERT INTO session_tool_calls "
        "(session_id, tool_use_id, tool_name, started_at, completed_at) "
        "VALUES (%s, %s, %s, %s, %s)",
        (
            session_id,
            tool_use_id,
            tool_name,
            _stamp(started_at or completed_at),
            _stamp(completed_at),
        ),
    )
    conn.commit()


def test_repaired_owner_start_is_timed_despite_stale_missing_event(
    test_db, monkeypatch
) -> None:
    _use_fixture_database(monkeypatch, test_db)
    completed = datetime.now(timezone.utc) - timedelta(minutes=20)
    started = completed - timedelta(milliseconds=1649)
    stale = _stamp(completed)
    _open_closed_call(
        test_db,
        session_id="cursor-session",
        tool_use_id="tu-repaired",
        completed_at=completed,
    )
    record_tool_call_started(
        test_db,
        session_id="cursor-session",
        tool_use_id="tu-repaired",
        tool_name="Read",
        started_at=_stamp(started),
    )
    test_db.commit()
    _insert_completion(
        test_db,
        event_id="stale-missing",
        session_id="cursor-session",
        tool_use_id="tu-repaired",
        executor="cursor",
        created_at=stale,
    )

    cursor_row = next(
        row
        for row in hook_overhead.tool_latency_rows(1)
        if row["scope"] == "harness" and row["harness"] == "cursor"
    )
    assert cursor_row["timed_count"] == 1
    assert cursor_row["pending_count"] == 0
    assert cursor_row["unknown_count"] == 0
    assert cursor_row["mean_ms"] == 1649
    assert cursor_row["comparison_status"] == "comparable"


def test_synthesized_start_inside_window_is_pending_not_incomplete(
    test_db, monkeypatch
) -> None:
    _use_fixture_database(monkeypatch, test_db)
    completed = datetime.now(timezone.utc)
    _open_closed_call(
        test_db,
        session_id="pending-session",
        tool_use_id="tu-pending",
        completed_at=completed,
    )
    _insert_completion(
        test_db,
        event_id="pending-missing",
        session_id="pending-session",
        tool_use_id="tu-pending",
        executor="cursor",
        created_at=_stamp(completed),
    )

    row = next(
        row for row in hook_overhead.tool_latency_rows(1) if row["scope"] == "global"
    )
    assert row["timed_count"] == 0
    assert row["pending_count"] == 1
    assert row["unknown_count"] == 0
    assert row["comparison_status"] == "pending"


def test_duplicate_completions_count_one_repaired_call(test_db, monkeypatch) -> None:
    _use_fixture_database(monkeypatch, test_db)
    completed = datetime.now(timezone.utc) - timedelta(minutes=20)
    started = completed - timedelta(milliseconds=400)
    stale = _stamp(completed)
    _open_closed_call(
        test_db,
        session_id="dup-session",
        tool_use_id="tu-dup",
        completed_at=completed,
        started_at=started,
    )
    _insert_completion(
        test_db,
        event_id="dup-a",
        session_id="dup-session",
        tool_use_id="tu-dup",
        executor="claude-code",
        created_at=stale,
    )
    _insert_completion(
        test_db,
        event_id="dup-b",
        session_id="dup-session",
        tool_use_id="tu-dup",
        executor="claude-code",
        created_at=stale,
    )

    row = next(
        row
        for row in hook_overhead.tool_latency_rows(1)
        if row["scope"] == "harness" and row["harness"] == "claude-code"
    )
    assert row["call_count"] == 1
    assert row["timed_count"] == 1
    assert row["mean_ms"] == 400


def test_fresh_and_resumed_supported_harnesses_read_owner_timing(
    test_db, monkeypatch
) -> None:
    _use_fixture_database(monkeypatch, test_db)
    completed = datetime.now(timezone.utc) - timedelta(minutes=20)
    stale = _stamp(completed)
    for session_id, tool_use_id, executor, elapsed in (
        ("fresh-cursor", "tu-fresh", "cursor", 80),
        ("resumed-codex", "tu-resumed", "codex", 120),
    ):
        started = completed - timedelta(milliseconds=elapsed)
        _open_closed_call(
            test_db,
            session_id=session_id,
            tool_use_id=tool_use_id,
            completed_at=completed,
            started_at=started,
        )
        _insert_completion(
            test_db,
            event_id=f"evt-{executor}",
            session_id=session_id,
            tool_use_id=tool_use_id,
            executor=executor,
            created_at=stale,
        )

    rows = {
        row["harness"]: row
        for row in hook_overhead.tool_latency_rows(1)
        if row["scope"] == "harness"
    }
    assert rows["cursor"]["timed_count"] == 1
    assert rows["cursor"]["unsupported_count"] == 0
    assert rows["codex"]["timed_count"] == 1
    assert rows["codex"]["mean_ms"] == 120


def test_out_of_order_start_supersedes_placeholder_before_report(
    test_db, monkeypatch
) -> None:
    _use_fixture_database(monkeypatch, test_db)
    completed = datetime.now(timezone.utc) - timedelta(minutes=20)
    started = completed - timedelta(milliseconds=250)
    _open_closed_call(
        test_db,
        session_id="reorder-session",
        tool_use_id="tu-reorder",
        completed_at=completed,
    )
    record_tool_call_started(
        test_db,
        session_id="reorder-session",
        tool_use_id="tu-reorder",
        tool_name="Grep",
        started_at=_stamp(started),
    )
    test_db.commit()
    _insert_completion(
        test_db,
        event_id="reorder-event",
        session_id="reorder-session",
        tool_use_id="tu-reorder",
        executor="cursor",
        created_at=_stamp(completed),
        tool_name="Grep",
    )

    row = next(
        row for row in hook_overhead.tool_latency_rows(1) if row["scope"] == "global"
    )
    assert row["mean_ms"] == 250
    assert row["comparison_status"] == "comparable"
    assert TIMING_PENDING_START_DELIVERY not in row["unsupported_timing_reason"]
