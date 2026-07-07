"""Persistence-layer tests for yoke_core.domain.reflection_capture.

Covers the persist_entries() boundary: DB round-trip, dedup, and error
surfacing. Parsing and end-to-end tests live in test_reflection_capture.py.
"""
from __future__ import annotations

from unittest import mock

import psycopg

from yoke_core.domain.reflection_capture import (
    ReflectionEntry,
    persist_entries,
)
from yoke_core.domain.schema_init_apply import execute_schema_script
from yoke_core.engines._doctor_native_sql_test_helpers import (
    connect_disposable_test_db,
)


def _make_reflection_db():
    """Create a disposable test DB with the ouroboros_entries table."""
    conn = connect_disposable_test_db()
    execute_schema_script(conn, """\
        CREATE TABLE projects (
            id INTEGER PRIMARY KEY,
            slug TEXT UNIQUE,
            name TEXT,
            public_item_prefix TEXT DEFAULT 'YOK'
        );
        INSERT INTO projects (id, slug, name, public_item_prefix)
        VALUES (1, 'yoke', 'Yoke', 'YOK');
        CREATE TABLE ouroboros_entries (
            id INTEGER PRIMARY KEY,
            timestamp TEXT NOT NULL,
            agent TEXT NOT NULL,
            context TEXT,
            category TEXT NOT NULL,
            body TEXT NOT NULL,
            reviewed_at TEXT,
            archived_at TEXT,
            project_id INTEGER,
            created_at TEXT NOT NULL DEFAULT ''
        );
    """)
    conn.commit()
    return conn


class TestPersistEntries:
    def test_persists_all_fields(self):
        conn = _make_reflection_db()
        entry = ReflectionEntry(
            timestamp="2026-04-12T10:30:00Z",
            agent="engineer",
            context="YOK-1216 task 3",
            category="friction",
            body="Multi-line\nobservation\nhere.",
        )

        result = persist_entries([entry], project="yoke", _conn=conn)

        assert result.entries_persisted == 1
        assert result.entries_skipped == 0
        assert result.errors == []

        row = conn.execute("SELECT * FROM ouroboros_entries WHERE id=1").fetchone()
        assert row["timestamp"] == "2026-04-12T10:30:00Z"
        assert row["agent"] == "engineer"
        assert row["context"] == "YOK-1216 task 3"
        assert row["category"] == "friction"
        assert row["body"] == "Multi-line\nobservation\nhere."
        assert row["project_id"] == 1
        conn.close()

    def test_dedup_skips_duplicate(self):
        conn = _make_reflection_db()
        entry = ReflectionEntry(
            timestamp="2026-04-12T10:30:00Z",
            agent="engineer",
            context="YOK-1216",
            category="friction",
            body="Same observation.",
        )

        r1 = persist_entries([entry], project="yoke", _conn=conn)
        r2 = persist_entries([entry], project="yoke", _conn=conn)

        assert r1.entries_persisted == 1
        assert r2.entries_skipped == 1
        assert r2.entries_persisted == 0
        count = conn.execute("SELECT COUNT(*) FROM ouroboros_entries").fetchone()[0]
        assert count == 1
        conn.close()

    def test_insert_error_surfaces_in_result(self):
        entry = ReflectionEntry(
            timestamp="2026-04-12T10:30:00Z",
            agent="engineer",
            context="test",
            category="problem",
            body="An observation.",
        )

        bad_conn = mock.MagicMock()
        bad_conn.execute.side_effect = psycopg.OperationalError("table not found")

        result = persist_entries([entry], _conn=bad_conn)

        assert result.entries_persisted == 0
        assert len(result.errors) == 1
        assert "Insert failed" in result.errors[0]


class TestBugLanguageGateExemption:
    def test_persists_body_with_banned_token(self):
        conn = _make_reflection_db()
        entry = ReflectionEntry(
            timestamp="2026-05-25T14:32:22Z",
            agent="engineer",
            context="YOK-1843 task 6",
            category="problems-encountered",
            body=(
                "Had to use a workaround to keep the test fixture stable "
                "while the parent harness refused to flush its in-memory cache."
            ),
        )

        result = persist_entries([entry], project="yoke", _conn=conn)

        assert result.entries_persisted == 1
        assert result.entries_skipped == 0
        assert result.errors == []
        body = conn.execute(
            "SELECT body FROM ouroboros_entries WHERE id=1"
        ).fetchone()["body"]
        assert "workaround" in body
        conn.close()


class TestPersistFailedEmission:
    def test_emits_event_when_insert_raises(self):
        entry = ReflectionEntry(
            timestamp="2026-04-12T10:30:00Z",
            agent="engineer",
            context="test",
            category="problem",
            body="A body excerpt with enough content to truncate." * 20,
        )

        bad_conn = mock.MagicMock()
        bad_conn.execute.side_effect = psycopg.OperationalError("table not found")

        with mock.patch(
            "yoke_core.domain.reflection_capture._emit_persist_failed"
        ) as emit:
            result = persist_entries([entry], _conn=bad_conn)

        assert result.entries_persisted == 0
        assert len(result.errors) == 1
        emit.assert_called_once()
        kwargs = emit.call_args.kwargs
        assert kwargs["agent"] == "engineer"
        assert kwargs["category"] == "problem"
        assert kwargs["body"].startswith("A body excerpt")
        assert isinstance(kwargs["exc"], psycopg.OperationalError)

    def test_emit_persist_failed_payload_shape(self):
        from yoke_core.domain.reflection_capture import _emit_persist_failed

        with mock.patch(
            "yoke_core.domain.events.emit_event"
        ) as emit_event:
            _emit_persist_failed(
                agent="tester",
                category="friction",
                body="x" * 500,
                exc=ValueError("boom"),
            )

        emit_event.assert_called_once()
        args, kwargs = emit_event.call_args
        assert args[0] == "ReflectionCapturePersistFailed"
        assert kwargs["event_kind"] == "hook"
        assert kwargs["event_type"] == "reflection_capture"
        ctx = kwargs["context"]
        assert ctx["agent"] == "tester"
        assert ctx["category"] == "friction"
        assert ctx["body_excerpt"] == "x" * 200
        assert len(ctx["body_excerpt"]) == 200
        assert ctx["exception_type"] == "ValueError"
