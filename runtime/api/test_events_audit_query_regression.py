"""Cross-cutting audit-query regression for YOK-1761.

The pre-YOK-1761 ledger silently false-success'd ``HarnessToolCallCompleted``
rows whose tool response carried a parseable nonzero ``Exit code N`` line
or a non-empty top-level ``error`` field. The five-value
``event_outcome`` enum plus the live emitters from tasks 001-003 (and
the historical backfill plus doctor HC in task 004) restore the
contract: the canonical audit query

    SELECT event_outcome, exit_code, item_id, session_id, event_name
    FROM events
    WHERE created_at >= :cutoff
      AND (event_outcome IN ('failed','denied','interrupted','structured_exit')
           OR exit_code > 0)

returns real failures from FIRST-CLASS COLUMNS, without falling back to
substring grep against the envelope JSON.

This regression drives three rows through the real ledger writer
(``yoke_core.domain.observe_event_emission.build_envelope`` +
``insert_event``) — one failing Bash call via the live parse path, one
dispatcher-attributed call, and one sentinel-completed orphan — and
asserts all three surface through the first-class query.
"""

from __future__ import annotations

import json
import uuid

import pytest

from yoke_core.domain.events_tool_call_outcome import (
    OUTCOME_FAILED,
    OUTCOME_INTERRUPTED,
    OUTCOMES,
)
from yoke_core.domain.observe_event_emission import build_envelope, insert_event
from yoke_core.domain.observe_parsing import EventRecord, parse_hook_event
from runtime.api.observe_test_helpers import make_memory_db


def _drive_observe_pipeline(
    conn, payload: dict, *, hook_event: str = "PostToolUse"
) -> None:
    """Drive the parser->envelope->insert real-producer path."""
    rec = parse_hook_event(payload, hook_event=hook_event)
    assert rec is not None
    envelope = build_envelope(rec)
    insert_event(conn, envelope)


def _emit_record(conn, rec: EventRecord) -> None:
    """Drive an EventRecord through the real build_envelope+insert path.

    Used for producers (dispatcher attribution, orphan-sweep sentinel)
    whose upstream wiring lives in sibling tasks: the EventRecord is the
    canonical contract between parser and envelope writer, so building
    one directly still exercises the real ledger writer rather than an
    inline insert. The recorded row is byte-identical to what the
    upstream producer would emit.
    """
    envelope = build_envelope(rec)
    insert_event(conn, envelope)


def _canonical_audit_query(conn, cutoff: str) -> list:
    """Run the canonical first-class-fields audit query."""
    rows = conn.execute(
        "SELECT event_outcome, exit_code, item_id, session_id, event_name, "
        "tool_use_id "
        "FROM events "
        "WHERE created_at >= %s "
        "  AND (event_outcome IN ('failed','denied','interrupted','structured_exit') "
        "       OR exit_code > 0) "
        "ORDER BY tool_use_id ASC",
        (cutoff,),
    ).fetchall()
    return rows


@pytest.fixture
def memory_db():
    conn = make_memory_db()
    yield conn
    conn.close()


def test_audit_query_returns_all_three_failure_kinds_by_first_class_columns(
    memory_db,
) -> None:
    """End-to-end: a failing Bash call, a dispatcher-attributed call, and
    an interrupted sentinel are all returned by the canonical audit
    query selecting first-class fields — no envelope grep required."""
    cutoff = "2026-01-01T00:00:00Z"

    # --- Producer 1: failing Bash via the real parse path -------------
    _drive_observe_pipeline(
        memory_db,
        {
            "tool_name": "Bash",
            "tool_input": {"command": "exit 7"},
            "tool_response": {"content": "Exit code 7"},
            "tool_use_id": "tu-aaa-bash-fail",
            "error": "Exit code 7",
        },
        hook_event="PostToolUseFailure",
    )

    # --- Producer 2: dispatcher-attributed failed call ---------------
    # Same envelope contract as the in-tree dispatcher emitter; the
    # attribution_source field is what the dispatcher wrapper stamps
    # so downstream queries can distinguish dispatcher-traced rows
    # from hook-traced rows.
    dispatcher_rec = EventRecord(
        tool_name="Bash",
        command="false",
        exit_code=1,
        is_failure=True,
        response_text="Exit code 1",
        hook_event="DispatchCallCompleted",
        session_id="sess-dispatcher",
        item_id="42",
        attribution_source="dispatcher",
        tool_use_id="tu-bbb-dispatcher",
    )
    _emit_record(memory_db, dispatcher_rec)

    # --- Producer 3: orphan-sweep sentinel ('interrupted') -----------
    # Same envelope contract as the in-tree orphan sweep emitter; the
    # sweep marks an unmatched PreToolUse row as 'interrupted' at
    # session end. The classifier's truth table does not produce
    # 'interrupted' from EventRecord state, so we insert the canonical
    # sentinel envelope directly through the same insert_event writer.
    sentinel_envelope = {
        "event_id": str(uuid.uuid4()),
        "event_name": "HarnessToolCallCompleted",
        "event_kind": "system",
        "event_type": "tool_call",
        "event_time": "2026-02-01T00:00:00.000Z",
        "event_outcome": OUTCOME_INTERRUPTED,
        "source_type": "agent",
        "severity": "WARN",
        "session_id": "sess-orphan",
        "service": "cli",
        "project": "yoke",
        "agent": None,
        "item_id": "99",
        "task_num": None,
        "tool_name": "Bash",
        "duration_ms": None,
        "exit_code": None,
        "anomaly_flags": "interrupted",
        "tool_use_id": "tu-ccc-sentinel",
        "turn_id": None,
        "hook_event_name": "SessionEnd",
        "context": {
            "detail": {
                "tool_name": "Bash",
                "sentinel_reason": {
                    "ending_session_id": "sess-orphan",
                    "sentinel_emitted_at": "2026-02-01T00:00:00.000Z",
                    "original_started_at": "2026-02-01T00:00:00.000Z",
                    "lifecycle_reason": "session_end_destructive",
                },
            }
        },
    }
    insert_event(memory_db, sentinel_envelope)
    memory_db.commit()

    # --- Run the canonical audit query -------------------------------
    rows = _canonical_audit_query(memory_db, cutoff)

    by_tool_use = {row["tool_use_id"]: row for row in rows}
    assert "tu-aaa-bash-fail" in by_tool_use, (
        "failing Bash row missing from canonical audit query"
    )
    assert "tu-bbb-dispatcher" in by_tool_use, (
        "dispatcher-attributed row missing from canonical audit query"
    )
    assert "tu-ccc-sentinel" in by_tool_use, (
        "interrupted sentinel row missing from canonical audit query"
    )

    # First-class column values must be honest.
    assert by_tool_use["tu-aaa-bash-fail"]["event_outcome"] == OUTCOME_FAILED
    assert by_tool_use["tu-aaa-bash-fail"]["exit_code"] == 7

    assert by_tool_use["tu-bbb-dispatcher"]["event_outcome"] == OUTCOME_FAILED
    assert by_tool_use["tu-bbb-dispatcher"]["exit_code"] == 1
    assert by_tool_use["tu-bbb-dispatcher"]["item_id"] == "42"

    assert by_tool_use["tu-ccc-sentinel"]["event_outcome"] == OUTCOME_INTERRUPTED
    assert by_tool_use["tu-ccc-sentinel"]["item_id"] == "99"

    # All returned outcomes belong to the five-value enum.
    for row in rows:
        assert (
            row["event_outcome"] in OUTCOMES
        ), f"unknown event_outcome {row['event_outcome']!r}"


def test_audit_query_excludes_clean_completed_rows(memory_db) -> None:
    """Negative regression: a successful Bash call MUST NOT surface."""
    cutoff = "2026-01-01T00:00:00Z"
    _drive_observe_pipeline(
        memory_db,
        {
            "tool_name": "Bash",
            "tool_input": {"command": "true"},
            "tool_response": {"content": "Exit code 0"},
            "tool_use_id": "tu-clean-success",
        },
        hook_event="PostToolUse",
    )

    rows = _canonical_audit_query(memory_db, cutoff)
    tool_use_ids = {row["tool_use_id"] for row in rows}
    assert "tu-clean-success" not in tool_use_ids


def test_audit_query_does_not_need_envelope_grep_to_find_failures(
    memory_db,
) -> None:
    """The whole point of YOK-1761 — substring grep against ``envelope``
    must NOT be required to recover failures. We assert the canonical
    query returns the failing row, then assert that the row's
    ``event_outcome`` is the explanation (not the envelope text)."""
    cutoff = "2026-01-01T00:00:00Z"
    _drive_observe_pipeline(
        memory_db,
        {
            "tool_name": "Bash",
            "tool_input": {"command": "exit 5"},
            "tool_response": {"content": "Exit code 5"},
            "tool_use_id": "tu-failure-source",
            "error": "Exit code 5",
        },
        hook_event="PostToolUseFailure",
    )

    rows = _canonical_audit_query(memory_db, cutoff)
    assert len(rows) == 1
    row = rows[0]

    # Honest first-class columns prove the failure without grep.
    assert row["event_outcome"] == OUTCOME_FAILED
    assert row["exit_code"] == 5

    # Negative defense: envelope substring grep is no longer the path.
    # If a future emitter regresses to false-success'ing this shape, the
    # canonical query would return zero rows and this test would FAIL
    # before any audit consumer needs to inspect the envelope text.


def test_audit_query_cutoff_respects_created_at(memory_db) -> None:
    """A failure recorded before the cutoff must not be returned."""
    # Seed a pre-cutoff row directly so we can control created_at.
    memory_db.execute(
        "INSERT INTO events (event_id, event_name, event_outcome, exit_code, "
        "tool_use_id, envelope, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (
            str(uuid.uuid4()),
            "HarnessToolCallFailed",
            OUTCOME_FAILED,
            3,
            "tu-too-old",
            json.dumps({}),
            "2025-12-31T00:00:00Z",
        ),
    )
    memory_db.commit()

    rows = _canonical_audit_query(memory_db, cutoff="2026-01-01T00:00:00Z")
    tool_use_ids = {row["tool_use_id"] for row in rows}
    assert "tu-too-old" not in tool_use_ids
