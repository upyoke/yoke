"""Tests for ``HC-work-claim-status-mismatch``."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from runtime.api.fixtures import pg_testdb
from yoke_core.domain import db_backend
from yoke_core.engines.doctor_hc_work_claim_status_mismatch import (
    hc_work_claim_status_mismatch,
)
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl


_FULL_DDL = """
CREATE TABLE work_claims (
 id INTEGER PRIMARY KEY, session_id TEXT NOT NULL, target_kind TEXT NOT NULL,
 item_id INTEGER, epic_id INTEGER, task_num INTEGER, process_key TEXT,
 claimed_at TEXT, last_heartbeat TEXT, released_at TEXT
);
CREATE TABLE items (id INTEGER PRIMARY KEY, status TEXT NOT NULL);
CREATE TABLE harness_sessions (
 session_id TEXT PRIMARY KEY, mode TEXT, ended_at TEXT, last_heartbeat TEXT
);
"""


def _iso_ago(minutes: float = 0) -> str:
    moment = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _apply_schema() -> None:
    conn = db_backend.connect()
    try:
        apply_fixture_ddl(conn, _FULL_DDL)
    finally:
        conn.close()


@pytest.fixture
def conn(tmp_path):
    with init_test_db(tmp_path, apply_schema=_apply_schema) as db_path:
        c = connect_test_db(db_path)
        try:
            yield c
        finally:
            c.close()


def _result(conn):
    rec = RecordCollector()
    hc_work_claim_status_mismatch(conn, DoctorArgs(), rec)
    return rec.results[-1]


def _seed(conn, *, session_id="s", mode="usher", minutes_ago=1.0,
          ended=False, item_id=100, status="release", claim_id=1,
          released_at=None, target_kind="item", **extra):
    p = _p(conn)
    conn.execute(
        "INSERT INTO harness_sessions (session_id, mode, ended_at, last_heartbeat) "
        f"VALUES ({p}, {p}, {p}, {p})",
        (session_id, mode, _iso_ago(0) if ended else None, _iso_ago(minutes_ago)),
    )
    conn.execute(
        f"INSERT INTO items (id, status) VALUES ({p}, {p})",
        (item_id, status),
    )
    conn.execute(
        "INSERT INTO work_claims (id, session_id, target_kind, item_id, "
        "epic_id, task_num, process_key, claimed_at, last_heartbeat, released_at) "
        f"VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})",
        (
            claim_id, session_id, target_kind,
            item_id if target_kind == "item" else None,
            extra.get("epic_id"), extra.get("task_num"), extra.get("process_key"),
            _iso_ago(5), _iso_ago(1), released_at,
        ),
    )
    conn.commit()


@pytest.mark.parametrize(
    "ddl",
    [
        "CREATE TABLE items (id INTEGER); "
        "CREATE TABLE harness_sessions (session_id TEXT);",
        "CREATE TABLE work_claims (id INTEGER); "
        "CREATE TABLE items (id INTEGER); "
        "CREATE TABLE harness_sessions (session_id TEXT);",
    ],
)
def test_passes_on_missing_or_minimal_schema(ddl):
    name = pg_testdb.create_test_database()
    c = pg_testdb.connect_test_database(name)
    apply_fixture_ddl(c, ddl)
    result = _result(c)
    c.close()
    pg_testdb.drop_test_database(name)
    assert result.result == "PASS"
    assert "skipping" in result.detail.lower()


@pytest.mark.parametrize(
    "kwargs",
    [
        None,
        {"session_id": "s-usher", "mode": "usher", "status": "release"},
        {"session_id": "s-idea", "mode": "idea", "status": "idea"},
        {"session_id": "s-refine", "mode": "refine", "status": "idea"},
        {"session_id": "s-eng", "mode": "advance", "status": "implementing"},
        {"session_id": "s-polish", "mode": "polish",
         "status": "polishing-implementation"},
        {
            "session_id": "s-old", "mode": "polish", "status": "release",
            "released_at": _iso_ago(2),
        },
        {
            "session_id": "s-task", "mode": "advance", "status": "release",
            "target_kind": "epic_task", "epic_id": 700, "task_num": 1,
        },
        {
            "session_id": "s-proc", "mode": "advance", "status": "release",
            "target_kind": "process", "process_key": "DOCTOR_PIPELINE",
        },
    ],
)
def test_passes_for_valid_or_out_of_scope_claims(conn, kwargs):
    if kwargs:
        _seed(conn, **kwargs)
    assert _result(conn).result == "PASS"


@pytest.mark.parametrize(
    "session_id, mode, status, minutes_ago, ended, item_id, expected",
    [
        ("s-polish", "polish", "release", 1, False, 500, "usher YOK-500"),
        ("s-stale", "usher", "release", 999, False, 501, "YOK-501"),
        ("s-ended", "usher", "release", 1, True, 502, " ended"),
        ("s-wander", "conduct", "idea", 1, False, 600, "stale draft claim"),
        ("s-stale-idea", "idea", "idea", 999, False, 601, "YOK-601"),
    ],
)
def test_warns_for_mismatched_claims(
    conn, session_id, mode, status, minutes_ago, ended, item_id, expected):
    _seed(conn, session_id=session_id, mode=mode, status=status,
          minutes_ago=minutes_ago, ended=ended, item_id=item_id)
    result = _result(conn)
    assert result.result == "WARN"
    assert expected in result.detail
