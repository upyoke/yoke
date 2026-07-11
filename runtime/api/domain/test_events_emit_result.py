"""Tests for structured outcomes from the native event emitter."""

from __future__ import annotations

import json

from yoke_core.domain.events import emit_event
from runtime.api.fixtures.pg_testdb import test_database


def _emit(conn=None):
    return emit_event(
        "TestEmitResult",
        event_kind="lifecycle",
        event_type="test",
        source_type="system",
        severity="INFO",
        item_id="1572",
        context={"detail": {"source": "test"}},
        conn=conn,
    )


def test_emit_event_returns_ok_result_and_event_id() -> None:
    with test_database() as conn:
        result = _emit(conn)

        assert result.ok is True
        assert result.reason == ""
        assert result.event_id
        assert result.get("event_id") == result.event_id
        row = conn.execute(
            "SELECT event_name, item_id, envelope FROM events WHERE event_id=%s",
            (result.event_id,),
        ).fetchone()
        assert row["event_name"] == "TestEmitResult"
        assert row["item_id"] == "1572"
        assert json.loads(row["envelope"])["context"]["detail"]["source"] == "test"


def test_emit_event_resolves_actor_id_from_session() -> None:
    with test_database() as conn:
        conn.execute(
            "INSERT INTO harness_sessions "
            "(session_id, executor, provider, model, execution_lane, workspace, "
            "offered_at, last_heartbeat, actor_id) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                "sess-actor",
                "codex",
                "openai",
                "gpt-5.5",
                "ALTMAN",
                "/tmp",
                "2026-06-09T00:00:00Z",
                "2026-06-09T00:00:00Z",
                2,
            ),
        )
        conn.commit()

        result = emit_event(
            "TestSessionActor",
            event_kind="system",
            event_type="test",
            source_type="backend",
            severity="INFO",
            session_id="sess-actor",
            conn=conn,
        )

        assert result.ok is True
        row = conn.execute(
            "SELECT actor_id, envelope FROM events WHERE event_id=%s",
            (result.event_id,),
        ).fetchone()
        assert row["actor_id"] == 2
        assert json.loads(row["envelope"])["actor_id"] == 2


def test_emit_event_persists_canonical_context_fields() -> None:
    with test_database() as conn:
        result = emit_event(
            "TestCanonicalContext",
            event_kind="system",
            event_type="test",
            source_type="backend",
            severity="INFO",
            session_id="sess-canonical",
            org_id="org-1",
            environment="stage",
            request_id="req-123",
            conn=conn,
        )

        assert result.ok is True
        row = conn.execute(
            "SELECT org_id, environment, envelope "
            "FROM events WHERE event_id=%s",
            (result.event_id,),
        ).fetchone()
        assert row["org_id"] == "org-1"
        assert row["environment"] == "stage"
        envelope = json.loads(row["envelope"])
        assert envelope["session_id"] == "sess-canonical"
        assert "user_id" not in envelope
        assert envelope["org_id"] == "org-1"
        assert envelope["environment"] == "stage"
        assert envelope["request_id"] == "req-123"


def test_emit_event_reports_missing_events_table() -> None:
    with test_database() as conn:
        conn.execute("DROP TABLE events")
        conn.commit()
        result = _emit(conn)

        assert result.ok is False
        assert result.reason == "events_table_missing"
        assert result.event_id is None


def test_emit_event_capture_mode_returns_reason(monkeypatch, tmp_path) -> None:
    capture = tmp_path / "events.jsonl"
    monkeypatch.setenv("YOKE_EVENTS_CAPTURE", "1")
    monkeypatch.setenv("YOKE_EVENTS_FILE", str(capture))

    result = _emit()

    assert result.ok is False
    assert result.reason == "capture_only"
    assert result.event_id
    captured = json.loads(capture.read_text(encoding="utf-8").strip())
    assert captured["event_id"] == result.event_id
