"""Tests for the Python emit-event owner."""

from __future__ import annotations

import json
from unittest.mock import patch

from yoke_core.domain import emit_event, events_crud
from runtime.api.fixtures.file_test_db import connect_test_db
from runtime.api.test_emit_event_test_helpers import (
    TEST_ITEM_ID,
    TEST_ITEM_REF,
    events_db,  # noqa: F401 — re-exported pytest fixture
)


def test_emit_wraps_context_and_error_payload(events_db):
    rc = emit_event.main(
        [
            "--name", "ContextEvent",
            "--kind", "system",
            "--type", "test",
            "--source-type", "agent",
            "--session-id", "ctx-session",
            "--event-id", "ctx-event-1",
            "--context", '{"key":"value"}',
            "--error-context", '{"error_category":"agent_failure","message":"boom"}',
        ]
    )

    assert rc == 0
    conn = connect_test_db(events_db)
    envelope = conn.execute(
        "SELECT envelope FROM events WHERE event_id='ctx-event-1'"
    ).fetchone()[0]
    conn.close()
    parsed = json.loads(envelope)
    assert parsed["context"]["detail"]["key"] == "value"
    assert parsed["context"]["error"]["error_category"] == "agent_failure"


def test_emit_persists_canonical_correlation_fields(events_db):
    rc = emit_event.main(
        [
            "--name", "CanonicalCorrelationEvent",
            "--kind", "system",
            "--type", "test",
            "--source-type", "agent",
            "--session-id", "correlation-session",
            "--event-id", "correlation-event-1",
            "--user-id", "user-1",
            "--org-id", "org-1",
            "--request-id", "req-1",
            "--environment", "stage",
        ]
    )

    assert rc == 0
    conn = connect_test_db(events_db)
    row = conn.execute(
        "SELECT user_id, org_id, environment, envelope "
        "FROM events WHERE event_id='correlation-event-1'"
    ).fetchone()
    conn.close()
    assert row[0] == "user-1"
    assert row[1] == "org-1"
    assert row[2] == "stage"
    envelope = json.loads(row[3])
    assert envelope["session_id"] == "correlation-session"
    assert envelope["user_id"] == "user-1"
    assert envelope["org_id"] == "org-1"
    assert envelope["environment"] == "stage"
    assert envelope["request_id"] == "req-1"


def test_emit_envelope_copies_active_trace_context(events_db):
    with patch(
        "yoke_core.api.observability.trace_context",
        return_value={"trace_id": "trace-1", "span_id": "span-1"},
    ):
        rc = emit_event.main(
            [
                "--name", "TraceCorrelationEvent",
                "--kind", "system",
                "--type", "test",
                "--source-type", "agent",
                "--session-id", "trace-session",
                "--event-id", "trace-event-1",
            ]
        )

    assert rc == 0
    conn = connect_test_db(events_db)
    envelope = conn.execute(
        "SELECT envelope FROM events WHERE event_id='trace-event-1'"
    ).fetchone()[0]
    conn.close()
    parsed = json.loads(envelope)
    assert parsed["trace_id"] == "trace-1"
    assert parsed["span_id"] == "span-1"


def test_emit_uses_session_fallback_chain(events_db, monkeypatch):
    monkeypatch.setenv("YOKE_SESSION_ID", "fallback-session")
    rc = emit_event.main(
        [
            "--name", "FallbackEvent",
            "--kind", "system",
            "--type", "test",
            "--source-type", "agent",
            "--event-id", "fallback-event-1",
        ]
    )

    assert rc == 0
    conn = connect_test_db(events_db)
    session_id = conn.execute(
        "SELECT session_id FROM events WHERE event_id='fallback-event-1'"
    ).fetchone()[0]
    conn.close()
    assert session_id == "fallback-session"


def test_emit_resolves_project_from_item_id(events_db):
    rc = emit_event.main(
        [
            "--name", "ProjectResolveEvent",
            "--kind", "system",
            "--type", "test",
            "--source-type", "agent",
            "--session-id", "project-session",
            "--event-id", "project-event-1",
            "--item-id", TEST_ITEM_REF,
        ]
    )

    assert rc == 0
    conn = connect_test_db(events_db)
    row = conn.execute(
        "SELECT project_id, item_id FROM events WHERE event_id='project-event-1'"
    ).fetchone()
    conn.close()
    assert row[0] == 2
    assert row[1] == str(TEST_ITEM_ID)


def test_emit_severity_drop_is_silent(events_db):
    events_crud.cmd_severity_config_set(events_db, "*", "*", "WARN")
    before = events_crud.cmd_count(events_db)

    rc = emit_event.main(
        [
            "--name", "DroppedEvent",
            "--kind", "system",
            "--type", "test",
            "--source-type", "agent",
            "--severity", "DEBUG",
            "--session-id", "drop-session",
            "--event-id", "dropped-event-1",
        ]
    )

    assert rc == 0
    assert events_crud.cmd_count(events_db) == before


def test_emit_rejects_invalid_error_category(events_db, capsys):
    rc = emit_event.main(
        [
            "--name", "BadCategoryEvent",
            "--kind", "system",
            "--type", "test",
            "--source-type", "agent",
            "--session-id", "bad-category-session",
            "--error-context", '{"error_category":"not_real"}',
        ]
    )

    captured = capsys.readouterr()
    assert rc == 2
    assert "invalid error_category" in captured.err
