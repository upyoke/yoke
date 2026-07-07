"""Tests for HC-reflection-capture-hook-coverage and HC-reflection-capture-unhandled."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
from yoke_core.engines.doctor_hc_reflection_capture_hook_coverage import (
    hc_reflection_capture_hook_coverage,
    hc_reflection_capture_unhandled,
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


def _insert_event(conn, event_name, tool_name=None, payload=None, age_hours=0):
    conn.execute(
        "INSERT INTO events(event_name, tool_name, payload, created_at) "
        "VALUES(%s, %s, %s, %s)",
        (event_name, tool_name,
         json.dumps(payload) if payload is not None else None,
         _stamp(age_hours)),
    )
    conn.commit()


class TestCoverageHC:
    def test_skips_when_events_table_missing(self):
        conn = _make_conn(with_events_table=False)
        rec = _FakeRecord()
        hc_reflection_capture_hook_coverage(conn, _FakeArgs(), rec)
        assert rec.records[0][2] == "PASS"
        assert "not present" in rec.records[0][3]

    def test_pass_when_no_agent_calls(self):
        conn = _make_conn()
        rec = _FakeRecord()
        hc_reflection_capture_hook_coverage(conn, _FakeArgs(), rec)
        assert rec.records[0][2] == "PASS"
        assert "no Agent-tool calls" in rec.records[0][3]

    def test_pass_when_all_calls_matched(self):
        conn = _make_conn()
        for ttid in ("toolu_01", "toolu_02"):
            _insert_event(conn, "HarnessToolCallCompleted",
                          tool_name="Agent", payload={"tool_use_id": ttid})
            _insert_event(conn, "ReflectionCaptureHookFired",
                          payload={"tool_use_id": ttid})
        rec = _FakeRecord()
        hc_reflection_capture_hook_coverage(conn, _FakeArgs(), rec)
        assert rec.records[0][2] == "PASS"
        assert "matching ReflectionCaptureHookFired" in rec.records[0][3]

    def test_fail_when_call_missing_fired_event(self):
        conn = _make_conn()
        _insert_event(conn, "HarnessToolCallCompleted",
                      tool_name="Agent", payload={"tool_use_id": "toolu_orphan"})
        rec = _FakeRecord()
        hc_reflection_capture_hook_coverage(conn, _FakeArgs(), rec)
        assert rec.records[0][2] == "FAIL"
        assert "toolu_orphan" in rec.records[0][3]


class TestUnhandledHC:
    def test_skips_when_events_table_missing(self):
        conn = _make_conn(with_events_table=False)
        rec = _FakeRecord()
        hc_reflection_capture_unhandled(conn, _FakeArgs(), rec)
        assert rec.records[0][2] == "PASS"

    def test_pass_when_no_unhandled_events(self):
        conn = _make_conn()
        rec = _FakeRecord()
        hc_reflection_capture_unhandled(conn, _FakeArgs(), rec)
        assert rec.records[0][2] == "PASS"
        assert "no ReflectionCaptureHookUnhandled" in rec.records[0][3]

    def test_warn_when_unhandled_present(self):
        conn = _make_conn()
        _insert_event(
            conn, "ReflectionCaptureHookUnhandled",
            payload={
                "tool_use_id": "toolu_03",
                "role": "engineer",
                "blocks_unrecognized": 1,
                "raw_examples": [
                    {"excerpt": "completely novel shape body...",
                     "classification_attempt": "unrecognized_shape"},
                ],
            },
        )
        rec = _FakeRecord()
        hc_reflection_capture_unhandled(conn, _FakeArgs(), rec)
        assert rec.records[0][2] == "WARN"
        assert "completely novel shape body" in rec.records[0][3]
        assert "engineer" in rec.records[0][3]

    def test_caps_detail_at_10_excerpts(self):
        conn = _make_conn()
        for i in range(15):
            _insert_event(
                conn, "ReflectionCaptureHookUnhandled",
                payload={"tool_use_id": f"toolu_{i:02d}", "blocks_unrecognized": 1,
                         "raw_examples": [{"excerpt": f"shape-{i}"}]},
            )
        rec = _FakeRecord()
        hc_reflection_capture_unhandled(conn, _FakeArgs(), rec)
        assert rec.records[0][2] == "WARN"
        assert "5 more" in rec.records[0][3]  # 15 - 10 cap
