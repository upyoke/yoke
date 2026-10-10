"""Dependency creation binds Native clocks or canonical explicit SQLite text."""

from datetime import datetime, timedelta, timezone
import sqlite3

import pytest

from yoke_contracts.timestamps import InvalidInstant, format_instant
from yoke_core.domain import item_dependency as dependencies


@pytest.fixture(params=["postgres", "sqlite"])
def clock_connection(request, test_db):
    if request.param == "postgres":
        conn = test_db
        prefix, clock_type = "CREATE TEMP TABLE", "TIMESTAMPTZ"
    else:
        conn = sqlite3.connect(":memory:")
        prefix, clock_type = "CREATE TABLE", "TEXT"
    conn.execute(f"""{prefix} item_dependencies (
        dependent_item_id INTEGER, blocking_item_id INTEGER, gate_point TEXT,
        satisfaction TEXT, source TEXT, session_id TEXT, rationale TEXT,
        evidence_json TEXT, created_at {clock_type} NOT NULL,
        UNIQUE (dependent_item_id, blocking_item_id, gate_point)
    )""")
    yield conn, request.param
    if request.param == "sqlite":
        conn.close()


@pytest.fixture
def isolated_edge_resolution(monkeypatch):
    monkeypatch.setattr(dependencies, "_edge_ids", lambda *_: (1, 2))
    monkeypatch.setattr(dependencies, "resolve_item_ref", lambda *_: 1)
    monkeypatch.setattr(
        dependencies, "require_authorable_satisfaction", lambda *_a, **_k: None
    )
    monkeypatch.setattr(dependencies, "_refresh_blocked_reasons", lambda *_: None)


@pytest.fixture(params=["add", "reconcile"])
def edge_writer(request):
    def write(conn):
        if request.param == "add":
            return dependencies.cmd_dependency_add(
                conn, "dependent", "blocking", "operator"
            )
        return dependencies.cmd_dependency_reconcile(
            conn,
            "operator",
            "dependent",
            stdin_lines=["dependent blocking activation status:done reason"],
        )

    return write


@pytest.mark.parametrize("offset", [0, 330, -240])
@pytest.mark.parametrize("microsecond", [0, 123456])
def test_dependency_clock_keeps_native_type_or_fixed_six_sqlite_bytes(
    clock_connection,
    isolated_edge_resolution,
    edge_writer,
    monkeypatch,
    offset,
    microsecond,
):
    conn, backend = clock_connection
    instant = datetime(1969, 12, 31, 23, 59, 59, microsecond, tzinfo=timezone.utc)
    supplied = instant.astimezone(timezone(timedelta(minutes=offset)))
    monkeypatch.setattr(dependencies, "now_iso", lambda: supplied)
    assert edge_writer(conn) == "OK"
    stored = conn.execute("SELECT created_at FROM item_dependencies").fetchone()[0]
    if backend == "postgres":
        assert isinstance(stored, datetime)
        assert stored == instant
        assert (
            conn.execute(
                "SELECT pg_typeof(created_at)::text FROM item_dependencies"
            ).fetchone()[0]
            == "timestamp with time zone"
        )
    else:
        assert stored == format_instant(instant)


@pytest.mark.parametrize("bad", [datetime(2026, 1, 1), "2026-01-01T00:00:00Z"])
def test_dependency_clock_refuses_non_native_producer_before_storage(
    clock_connection, isolated_edge_resolution, edge_writer, monkeypatch, bad
):
    conn, _ = clock_connection
    monkeypatch.setattr(dependencies, "now_iso", lambda: bad)
    with pytest.raises(InvalidInstant, match="invalid_instant"):
        edge_writer(conn)
    assert conn.execute("SELECT count(*) FROM item_dependencies").fetchone()[0] == 0


@pytest.mark.parametrize("bad", [datetime(2026, 1, 1), "2026-01-01T00:00:00Z"])
def test_reconcile_invalid_clock_keeps_previous_dependency_bytes(
    clock_connection, isolated_edge_resolution, monkeypatch, bad
):
    conn, _ = clock_connection
    original = datetime(1969, 12, 31, 23, 59, 59, 123456, tzinfo=timezone.utc)
    monkeypatch.setattr(dependencies, "now_iso", lambda: original)
    dependencies.cmd_dependency_add(conn, "dependent", "blocking", "operator")
    before = tuple(conn.execute("SELECT * FROM item_dependencies").fetchone())
    monkeypatch.setattr(dependencies, "now_iso", lambda: bad)
    with pytest.raises(InvalidInstant, match="invalid_instant"):
        dependencies.cmd_dependency_reconcile(
            conn,
            "operator",
            "dependent",
            stdin_lines=["dependent blocking activation status:done replacement"],
        )
    after = tuple(conn.execute("SELECT * FROM item_dependencies").fetchone())
    assert after == before
