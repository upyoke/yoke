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
from yoke_core.domain.work_claim_targets import encode_scope


_FULL_DDL = """
CREATE TABLE work_claims (
 id INTEGER PRIMARY KEY, session_id TEXT NOT NULL, target_kind TEXT NOT NULL,
 scope TEXT NOT NULL,
 claimed_at TIMESTAMPTZ, last_heartbeat TIMESTAMPTZ, released_at TIMESTAMPTZ
);
CREATE TABLE projects (id INTEGER PRIMARY KEY, slug TEXT, public_item_prefix TEXT);
INSERT INTO projects (id, slug, public_item_prefix) VALUES (1, 'yoke', 'YOK');
CREATE TABLE items (
    id INTEGER PRIMARY KEY,
    project_id INTEGER,
    project_sequence INTEGER,
    status TEXT NOT NULL
);
CREATE TABLE harness_sessions (
 session_id TEXT PRIMARY KEY, mode TEXT, ended_at TIMESTAMPTZ, last_heartbeat TIMESTAMPTZ
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


def _seed(
    conn,
    *,
    session_id="s",
    mode="wait",
    minutes_ago=1.0,
    ended=False,
    item_id=100,
    status="release",
    claim_id=1,
    released_at=None,
    target_kind="item",
    **extra,
):
    p = _p(conn)
    conn.execute(
        "INSERT INTO harness_sessions (session_id, mode, ended_at, last_heartbeat) "
        f"VALUES ({p}, {p}, {p}, {p})",
        (session_id, mode, _iso_ago(0) if ended else None, _iso_ago(minutes_ago)),
    )
    # The finding names the item by reference, so the row it reads exists.
    conn.execute(
        f"INSERT INTO items (id, project_id, project_sequence, status)"
        f" VALUES ({p}, 1, {p}, {p})",
        (item_id, item_id, status),
    )
    conn.execute(
        "INSERT INTO work_claims (id, session_id, target_kind, scope, "
        "claimed_at, last_heartbeat, released_at) "
        f"VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p})",
        (
            claim_id,
            session_id,
            target_kind,
            encode_scope(
                {"item_id": item_id}
                if target_kind == "item"
                else {
                    "epic_id": extra["epic_id"],
                    "task_num": extra["task_num"],
                }
                if target_kind == "epic_task"
                else {
                    "process_key": extra["process_key"],
                    "conflict_group": "doctor:test",
                }
            ),
            _iso_ago(5),
            _iso_ago(1),
            released_at,
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
        {"session_id": "s-release", "status": "release"},
        {"session_id": "s-idea", "status": "idea"},
        # An old skill mode on a fresh holder is no finding: freshness decides.
        {"session_id": "s-polish", "mode": "polish", "status": "release"},
        {"session_id": "s-conduct", "mode": "conduct", "status": "idea"},
        {"session_id": "s-eng", "status": "implementing", "minutes_ago": 999},
        {
            "session_id": "s-old",
            "status": "release",
            "minutes_ago": 999,
            "released_at": _iso_ago(2),
        },
        {
            "session_id": "s-task",
            "status": "release",
            "minutes_ago": 999,
            "target_kind": "epic_task",
            "epic_id": 700,
            "task_num": 1,
        },
        {
            "session_id": "s-proc",
            "status": "release",
            "minutes_ago": 999,
            "target_kind": "process",
            "process_key": "DOCTOR_PIPELINE",
        },
    ],
)
def test_passes_for_fresh_or_out_of_scope_claims(conn, kwargs):
    if kwargs:
        _seed(conn, **kwargs)
    assert _result(conn).result == "PASS"


@pytest.mark.parametrize(
    "session_id, status, minutes_ago, ended, item_id, expected",
    [
        ("s-stale", "release", 999, False, 501, "usher YOK-501"),
        ("s-ended", "release", 1, True, 502, " ended"),
        ("s-stale-idea", "idea", 999, False, 601, "stale draft claim"),
    ],
)
def test_warns_for_claims_without_a_fresh_holder(
    conn, session_id, status, minutes_ago, ended, item_id, expected
):
    _seed(
        conn,
        session_id=session_id,
        status=status,
        minutes_ago=minutes_ago,
        ended=ended,
        item_id=item_id,
    )
    result = _result(conn)
    assert result.result == "WARN"
    assert expected in result.detail
    assert "mode=" not in result.detail
    assert "yoke claims work release --item YOK-N" in result.detail
    assert "service_client" not in result.detail


@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "Asia/Kathmandu"])
def test_native_holder_heartbeat_keeps_exact_freshness_boundary(
    conn, monkeypatch, zone
):
    from yoke_contracts.timestamps import parse_instant
    from yoke_core.engines import doctor_hc_work_claim_status_mismatch as owner

    stamp = parse_instant("1969-12-31T23:59:59.123456Z")
    conn.execute("SELECT set_config('TimeZone', %s, false)", (zone,))
    _seed(conn)
    monkeypatch.setattr(owner, "utc_now", lambda: stamp)
    monkeypatch.setattr(owner, "get_int", lambda *args: 20)
    boundary = stamp - timedelta(minutes=20)
    conn.execute("UPDATE harness_sessions SET last_heartbeat=%s", (boundary,))
    conn.commit()
    assert _result(conn).result == "PASS"
    conn.execute(
        "UPDATE harness_sessions SET last_heartbeat=%s",
        (boundary - timedelta(microseconds=1),),
    )
    conn.commit()
    assert _result(conn).result == "WARN"
