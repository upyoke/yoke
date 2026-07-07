"""Postgres backend probes for the native authority connection."""

from __future__ import annotations

from pathlib import Path
import uuid

import psycopg
import pytest

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.sql_json import json_get
from yoke_core.domain.time_sql import now_sql
from runtime.api.fixtures.pg_testdb import test_database as pg_test_database


@pytest.fixture
def pg_authority():
    with pg_test_database():
        yield


class _DummyConn:
    def __init__(self):
        self.closed = 0

    def close(self):
        self.closed += 1


def test_postgres_is_the_only_runtime_backend():
    assert db_backend.is_postgres()


def test_sqlite_to_postgres_bridge_modules_are_removed():
    retired_stems = {
        "db_backend_" + "sqlite_compat",
        "db_backend_pg_" + "trans" + "late",
        "db_backend_" + "pg_shims",
    }
    backend_dir = Path(db_backend.__file__).parent
    present = sorted(
        path.name
        for path in backend_dir.glob("db_backend_*.py")
        if path.stem in retired_stems
    )

    assert present == []


def test_connect_returns_native_psycopg_rows(pg_authority):
    conn = db_backend.connect()
    try:
        assert isinstance(conn, psycopg.Connection)
        assert db_backend.connection_is_postgres(conn)
        assert not hasattr(conn, "executescript")

        row = conn.execute(
            "SELECT %s::int AS n, %s::text AS label",
            (7, "native"),
        ).fetchone()

        assert row == {"n": 7, "label": "native"}
        assert row[0] == 7
        assert row["label"] == "native"
    finally:
        conn.close()


def test_test_connection_tracker_disabled_by_default(monkeypatch):
    db_backend.close_tracked_test_connections()
    monkeypatch.delenv(db_backend.TEST_TRACK_CONNECTIONS_ENV, raising=False)
    conn = _DummyConn()

    assert db_backend._track_test_connection(conn) is conn
    db_backend.close_tracked_test_connections()

    assert conn.closed == 0


def test_test_connection_tracker_closes_enabled_connections(monkeypatch):
    db_backend.close_tracked_test_connections()
    monkeypatch.setenv(db_backend.TEST_TRACK_CONNECTIONS_ENV, "1")
    first = _DummyConn()
    second = _DummyConn()

    db_backend._track_test_connection(first)
    db_backend._track_test_connection(second)
    db_backend.close_tracked_test_connections()
    db_backend.close_tracked_test_connections()

    assert first.closed == 1
    assert second.closed == 1


def test_test_connection_tracker_closes_only_connections_after_snapshot(monkeypatch):
    db_backend.close_tracked_test_connections()
    monkeypatch.setenv(db_backend.TEST_TRACK_CONNECTIONS_ENV, "1")
    fixture_conn = _DummyConn()
    test_conn = _DummyConn()

    db_backend._track_test_connection(fixture_conn)
    baseline = db_backend.tracked_test_connection_count()
    db_backend._track_test_connection(test_conn)
    db_backend.close_tracked_test_connections_since(baseline)

    assert fixture_conn.closed == 0
    assert test_conn.closed == 1
    db_backend.close_tracked_test_connections()
    assert fixture_conn.closed == 1


def test_native_connection_rejects_sqlite_paramstyle(pg_authority):
    conn = db_backend.connect()
    try:
        with pytest.raises(psycopg.Error):
            conn.execute("SELECT ?::int AS n", (1,))
        conn.rollback()
    finally:
        conn.close()


def test_roundtrip_on_active_backend_uses_returning(pg_authority):
    conn = db_backend.connect()
    title = f"native portability probe {uuid.uuid4().hex}"
    now = iso8601_now()
    try:
        row = conn.execute(
            "INSERT INTO items "
            "(title, type, status, project_id, project_sequence, "
            "created_at, updated_at) "
            "VALUES ("
            "%s, 'issue', 'idea', 1, "
            "COALESCE((SELECT MAX(project_sequence) + 1 FROM items "
            "WHERE project_id = 1), 1), %s, %s"
            ") RETURNING id",
            (title, now, now),
        ).fetchone()
        new_id = row["id"]
        assert new_id is not None and int(new_id) > 0
        conn.commit()

        row = conn.execute(
            "SELECT id, title, status FROM items WHERE id = %s",
            (new_id,),
        ).fetchone()
        assert row["title"] == title
        assert row["status"] == "idea"

        recent = conn.execute(
            f"SELECT COUNT(*) AS count FROM items "
            f"WHERE created_at >= {now_sql(offset_days=-1)}"
        ).fetchone()
        assert recent["count"] >= 1
    finally:
        conn.close()


def test_json_get_on_active_backend(pg_authority):
    conn = db_backend.connect()
    event_id = f"native-json-probe-{uuid.uuid4().hex}"
    now = iso8601_now()
    try:
        conn.execute(
            "INSERT INTO events "
            "(event_id, source_type, session_id, event_kind, event_type, "
            "event_name, envelope, created_at) "
            "VALUES (%s, 'system', 'native-json-probe', 'system', 'probe', "
            "'NativeJsonProbe', %s, %s)",
            (
                event_id,
                '{"browser_testable": true, "nested": {"n": 7}}',
                now,
            ),
        )

        frag = json_get("envelope", "$.nested.n")
        row = conn.execute(
            f"SELECT {frag} AS v FROM events WHERE event_id = %s",
            (event_id,),
        ).fetchone()
        assert row["v"] == "7"
    finally:
        conn.rollback()
        conn.close()
