"""Tests for HC-stop-hook-chain-end-deferred and Stop-chain membership."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from yoke_core.engines.doctor_hc_stop_hook_chain import (
    _HC_NAME,
    _MEMBER_NAME,
    hc_stop_hook_chain_end_deferred,
)
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl


_SCHEMA = """
CREATE TABLE events (
    id INTEGER PRIMARY KEY,
    event_name TEXT NOT NULL,
    session_id TEXT,
    item_id INTEGER,
    created_at TEXT NOT NULL,
    hook_event_name TEXT,
    envelope TEXT DEFAULT '{}'
);
"""


def _make_conn():
    """Disposable per-call Postgres test DB with the minimal events table."""
    from yoke_core.domain import db_backend

    from runtime.api.fixtures import pg_testdb

    name = pg_testdb.create_test_database()
    new_dsn = pg_testdb.dsn_for_test_database(name)
    prior = os.environ.get(db_backend.PG_DSN_ENV)
    os.environ[db_backend.PG_DSN_ENV] = new_dsn
    c = db_backend.connect()
    apply_fixture_ddl(c, _SCHEMA)

    _base_close = c.close

    def _close_and_drop():
        _base_close()
        if prior is not None:
            os.environ[db_backend.PG_DSN_ENV] = prior
        else:
            os.environ.pop(db_backend.PG_DSN_ENV, None)
        pg_testdb.drop_test_database(name)

    c.close = _close_and_drop
    return c


@pytest.fixture
def conn():
    c = _make_conn()
    yield c
    c.close()


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _emit_event(
    conn,
    name: str,
    session_id: str,
    *,
    item_id=None,
    age_minutes=0,
    hook_event_name=None,
    envelope=None,
):
    """Insert an event row dated ``age_minutes`` ago."""
    when = datetime.now(timezone.utc) - timedelta(minutes=age_minutes)
    conn.execute(
        "INSERT INTO events (event_name, session_id, item_id, created_at, "
        "hook_event_name, envelope) VALUES (%s, %s, %s, %s, %s, %s)",
        (
            name,
            session_id,
            item_id,
            _iso(when),
            hook_event_name,
            json.dumps(envelope or {}),
        ),
    )
    conn.commit()


def _run_hc(conn) -> RecordCollector:
    rec = RecordCollector()
    hc_stop_hook_chain_end_deferred(conn, DoctorArgs(), rec)
    return rec


def _named(rec: RecordCollector, check_id: str):
    return next(row for row in rec.results if row.check_id == check_id)


def test_membership_covers_promised_work_gate_and_dispatch(conn):
    rec = _run_hc(conn)
    assert _named(rec, _MEMBER_NAME).result == "PASS"


def test_pass_when_events_table_missing():
    """The HC self-skips cleanly when the events table is absent."""
    from runtime.api.fixtures import pg_testdb

    name = pg_testdb.create_test_database()
    c = pg_testdb.drop_database_on_close(
        pg_testdb.connect_test_database(name),
        name,
    )
    rec = _run_hc(c)
    c.close()
    assert _named(rec, _HC_NAME).result == "PASS"
    assert "events table missing" in _named(rec, _HC_NAME).detail


def test_pass_when_no_chain_end_deferred_events(conn):
    rec = _run_hc(conn)
    assert _named(rec, _HC_NAME).result == "PASS"


def test_pass_when_recent_events_within_stale_window(conn):
    """Events younger than the 60-minute stale window are not yet stranded."""
    _emit_event(conn, "ChainEndDeferred", "sess-recent", item_id=10, age_minutes=30)
    rec = _run_hc(conn)
    assert _named(rec, _HC_NAME).result == "PASS"


def test_pass_when_followup_session_ended_present(conn):
    """A ChainEndDeferred followed by HarnessSessionEnded is fine."""
    _emit_event(conn, "ChainEndDeferred", "sess-finished", item_id=10, age_minutes=120)
    _emit_event(conn, "HarnessSessionEnded", "sess-finished", age_minutes=10)
    rec = _run_hc(conn)
    assert _named(rec, _HC_NAME).result == "PASS"


def test_pass_when_cap_reached_record_present(conn):
    _emit_event(
        conn,
        "ChainEndDeferred",
        "sess-capped",
        item_id=7,
        age_minutes=120,
        envelope={
            "context": {"reason": "reinjection_cap_reached", "cap_reached": True}
        },
    )
    rec = _run_hc(conn)
    assert _named(rec, _HC_NAME).result == "PASS"


def test_pass_when_later_tool_use_present(conn):
    _emit_event(conn, "ChainEndDeferred", "sess-worked", item_id=8, age_minutes=120)
    _emit_event(
        conn,
        "HookGuardrailEvaluated",
        "sess-worked",
        age_minutes=10,
        hook_event_name="PreToolUse",
    )
    rec = _run_hc(conn)
    assert _named(rec, _HC_NAME).result == "PASS"


def test_pass_when_terminal_status_change_present(conn):
    _emit_event(conn, "ChainEndDeferred", "sess-done", item_id=9, age_minutes=120)
    _emit_event(
        conn,
        "ItemStatusChanged",
        "sess-done",
        item_id=9,
        age_minutes=10,
        envelope={"context": {"to_status": "done"}},
    )
    rec = _run_hc(conn)
    assert _named(rec, _HC_NAME).result == "PASS"


def test_warn_when_deferred_event_aged_past_stale_window(conn):
    """A ChainEndDeferred older than 60min with no follow-up end fires WARN."""
    _emit_event(conn, "ChainEndDeferred", "sess-stranded", item_id=42, age_minutes=120)
    rec = _run_hc(conn)
    row = _named(rec, _HC_NAME)
    assert row.result == "WARN"
    assert "sess-stranded" in row.detail
    assert "42" in row.detail


def test_warn_caps_at_ten_listings_with_overflow_summary(conn):
    """The HC lists the first 10 stranded sessions and summarizes the rest."""
    for i in range(15):
        _emit_event(
            conn,
            "ChainEndDeferred",
            f"sess-stranded-{i:02d}",
            item_id=i + 1,
            age_minutes=120,
        )
    rec = _run_hc(conn)
    msg = _named(rec, _HC_NAME).detail
    assert _named(rec, _HC_NAME).result == "WARN"
    assert "15 ChainEndDeferred" in msg
    assert "and 5 more" in msg
