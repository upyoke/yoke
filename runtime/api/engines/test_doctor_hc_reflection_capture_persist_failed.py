"""Tests for HC-reflection-capture-persist-failed."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
from yoke_core.engines.doctor_hc_reflection_capture_persist_failed import (
    hc_reflection_capture_persist_failed,
)


class _FakeRecord:
    def __init__(self):
        self.records: list[tuple[str, str, str, str]] = []

    def record(self, name: str, desc: str, status: str, detail: str) -> None:
        self.records.append((name, desc, status, detail))


class _FakeArgs:
    pass


def _make_conn(*, with_events_table: bool = True) -> Any:
    name = pg_testdb.create_test_database()
    conn = pg_testdb.connect_test_database(name)
    if with_events_table:
        apply_fixture_ddl(conn, """
            CREATE TABLE events (
                id INTEGER PRIMARY KEY,
                event_name TEXT NOT NULL,
                tool_name TEXT,
                payload TEXT,
                created_at TEXT NOT NULL DEFAULT (now()::text)
            )
        """)
    return pg_testdb.drop_database_on_close(conn, name)


def _stamp(age_hours: int = 0) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=age_hours)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _insert_event(conn, event_name, payload=None, age_hours=0):
    conn.execute(
        "INSERT INTO events(event_name, payload, created_at) "
        "VALUES(%s, %s, %s)",
        (event_name,
         json.dumps(payload) if payload is not None else None,
         _stamp(age_hours)),
    )
    conn.commit()


class TestPersistFailedHC:
    def test_skips_when_events_table_missing(self):
        conn = _make_conn(with_events_table=False)
        rec = _FakeRecord()
        hc_reflection_capture_persist_failed(conn, _FakeArgs(), rec)
        assert rec.records[0][2] == "PASS"
        assert "not present" in rec.records[0][3]

    def test_pass_when_no_persist_failed_events(self):
        conn = _make_conn()
        rec = _FakeRecord()
        hc_reflection_capture_persist_failed(conn, _FakeArgs(), rec)
        assert rec.records[0][2] == "PASS"
        assert "no ReflectionCapturePersistFailed" in rec.records[0][3]

    def test_warn_when_persist_failed_present(self):
        conn = _make_conn()
        _insert_event(
            conn, "ReflectionCapturePersistFailed",
            payload={
                "agent": "engineer",
                "category": "problems-encountered",
                "body_excerpt": "Had to use a workaround to keep the test stable.",
                "exception_type": "OperationalError",
            },
        )
        rec = _FakeRecord()
        hc_reflection_capture_persist_failed(conn, _FakeArgs(), rec)
        assert rec.records[0][2] == "WARN"
        detail = rec.records[0][3]
        assert "engineer" in detail
        assert "problems-encountered" in detail
        assert "workaround" in detail

    def test_aggregates_by_category_and_exception(self):
        conn = _make_conn()
        for category, exc in (
            ("friction", "OperationalError"),
            ("friction", "OperationalError"),
            ("friction", "ValueError"),
            ("game-changing-ideas", "OperationalError"),
        ):
            _insert_event(
                conn, "ReflectionCapturePersistFailed",
                payload={
                    "agent": "tester", "category": category,
                    "body_excerpt": "x", "exception_type": exc,
                },
            )
        rec = _FakeRecord()
        hc_reflection_capture_persist_failed(conn, _FakeArgs(), rec)
        assert rec.records[0][2] == "WARN"
        detail = rec.records[0][3]
        assert "friction=3" in detail
        assert "game-changing-ideas=1" in detail
        assert "OperationalError=3" in detail
        assert "ValueError=1" in detail

    def test_caps_detail_at_10_excerpts(self):
        conn = _make_conn()
        for i in range(15):
            _insert_event(
                conn, "ReflectionCapturePersistFailed",
                payload={
                    "agent": "engineer", "category": "friction",
                    "body_excerpt": f"excerpt-{i}",
                    "exception_type": "OperationalError",
                },
            )
        rec = _FakeRecord()
        hc_reflection_capture_persist_failed(conn, _FakeArgs(), rec)
        assert rec.records[0][2] == "WARN"
        assert "5 more" in rec.records[0][3]

    def test_ignores_events_older_than_24h(self):
        conn = _make_conn()
        _insert_event(
            conn, "ReflectionCapturePersistFailed",
            payload={"agent": "engineer", "category": "friction",
                     "body_excerpt": "stale", "exception_type": "X"},
            age_hours=48,
        )
        rec = _FakeRecord()
        hc_reflection_capture_persist_failed(conn, _FakeArgs(), rec)
        assert rec.records[0][2] == "PASS"
