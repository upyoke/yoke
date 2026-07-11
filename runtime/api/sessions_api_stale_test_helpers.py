"""Shared time helpers and DB-fixture builders for ``test_sessions_api_stale*``.

Filename omits the ``test_`` prefix so pytest does not collect it. Each split
file imports the helpers it needs and (where the helper is fixture-shaped)
wraps it in a local ``@pytest.fixture`` shim. This keeps fixtures local to
their consumer files while sharing the verbose schema DDL and time literals.

Postgres connection fixtures (``conn`` / ``ownership_conn``) live here too.
They route through :func:`init_test_db` so the schema/seed bodies reused from
``runtime.api.test_sessions`` are built on the same disposable Postgres DB the
production paths read.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from yoke_core.domain import db_backend
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl


def _ago_minutes(n: int) -> str:
    """Return a UTC ISO-8601 literal timestamp for ``now - n minutes``.

    Portable-SQL tests cannot use SQL-side arithmetic; bind this literal
    into the query from Python instead.
    """
    return (datetime.now(timezone.utc) - timedelta(minutes=n)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _now_literal() -> str:
    """Return a UTC ISO-8601 literal timestamp for ``now``."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def apply_ddl_statements(conn: Any, *ddl_blocks: str) -> None:
    """Apply fixture DDL through the connection's native ``execute`` surface.

    These session/service-client fixtures use statement-by-statement setup so
    Postgres setup does not depend on compatibility-era script execution.
    """
    apply_fixture_ddl(conn, "\n".join(ddl_blocks))


# Schema for the lightweight events table used by ``conn_with_events`` fixtures
# in TestCleanStaleHarnessSessions and TestStaleReclaimYOK1350. Both classes
# create the same minimal events table to drive multi-signal stale detection.
# Mirrors the production indexed ``session_id`` column that stale-cleanup queries
# read directly — the JSON-path lookup that used to back this code is a 15000x
# slower full scan on a real-size events table.
EVENTS_TABLE_FOR_STALE_DETECTION = """
    CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY,
        event_name TEXT NOT NULL,
        event_type TEXT NOT NULL DEFAULT 'system',
        source_type TEXT,
        severity TEXT DEFAULT 'INFO',
        org_id TEXT,
        environment TEXT,
        created_at TEXT NOT NULL,
        session_id TEXT,
        envelope TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_events_session_id ON events(session_id);
"""


@pytest.fixture
def conn(tmp_path):
    """Postgres replacement for the old in-memory ``conn`` fixture.

    Disposable per-test Postgres DB with ``YOKE_PG_DSN`` repointed for the
    context's lifetime. The
    schema is the same one ``runtime.api.test_sessions._create_schema`` builds.
    The ``with`` stays open across the yield so the connection and the
    introspection shims share the per-test DB for the whole test.
    """
    from runtime.api.test_sessions import _create_schema

    with init_test_db(tmp_path, apply_schema=lambda: _build_schema(_create_schema)):
        c = connect_test_db(str(tmp_path / "yoke.db"))
        try:
            yield c
        finally:
            c.close()


@pytest.fixture
def ownership_conn(tmp_path):
    """Postgres replacement for the file-based ``ownership_conn`` fixture.

    Mirrors ``runtime.api.test_sessions.ownership_conn``: full ownership schema,
    a seeded runnable item (id 100), and the strategy SML files the scheduler
    coherence check reads.
    """
    from runtime.api.test_sessions import _create_ownership_schema

    with init_test_db(
        tmp_path, apply_schema=lambda: _build_ownership_schema(_create_ownership_schema)
    ):
        c = connect_test_db(str(tmp_path / "yoke.db"))
        # Seed a runnable item (matches the legacy fixture).
        c.execute(
            "INSERT INTO items (id, title, type, status, priority, project_id, "
            "created_at, updated_at, source, frozen) VALUES "
            "(100, 'Test item', 'issue', 'refined-idea', 'high', 1, "
            "'2026-03-01', '2026-03-01', 'user', 0)"
        )
        c.commit()
        ws = str(tmp_path)
        (tmp_path / ".yoke" / "strategy").mkdir(parents=True, exist_ok=True)
        for sml_file in ("MISSION.md", "LANDSCAPE.md", "VISION.md", "MASTER-PLAN.md"):
            (tmp_path / ".yoke" / "strategy" / sml_file).write_text(
                f"# {sml_file}\n"
            )
        try:
            yield c, ws
        finally:
            c.close()


def _build_schema(create_schema) -> None:
    """``init_test_db`` applier: build the session schema on the backend conn."""
    conn = db_backend.connect()
    try:
        create_schema(conn)
        conn.commit()
    finally:
        conn.close()


# Tables the ownership-reclaim path (register_session -> actor resolution; the
# reclaim emit -> native event emitter + retired-name guard) reads but that
# ``_create_ownership_schema`` does not build. Missing relations poison a
# Postgres transaction, so the empty tables must exist.
_OWNERSHIP_EXTRA_TABLES = """
    CREATE TABLE IF NOT EXISTS actors (
        id INTEGER PRIMARY KEY,
        kind TEXT NOT NULL DEFAULT 'system',
        system_component TEXT,
        created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY,
        event_id TEXT UNIQUE,
        event_name TEXT NOT NULL,
        event_kind TEXT,
        event_type TEXT NOT NULL DEFAULT 'system',
        source_type TEXT,
        session_id TEXT,
        severity TEXT DEFAULT 'INFO',
        event_outcome TEXT,
        org_id TEXT,
        environment TEXT,
        service TEXT,
        project_id INTEGER,
        item_id TEXT,
        task_num INTEGER,
        agent TEXT,
        tool_name TEXT,
        duration_ms INTEGER,
        trace_id TEXT,
        parent_id TEXT,
        anomaly_flags TEXT,
        tool_use_id TEXT,
        turn_id TEXT,
        hook_event_name TEXT,
        envelope TEXT,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS event_registry (
        event_name TEXT PRIMARY KEY,
        owner_service TEXT,
        status TEXT
    );
"""


def _build_ownership_schema(create_ownership_schema) -> None:
    """``init_test_db`` applier: build the ownership schema on the backend conn."""
    conn = db_backend.connect()
    try:
        create_ownership_schema(conn)
        apply_ddl_statements(conn, _OWNERSHIP_EXTRA_TABLES)
        conn.commit()
    finally:
        conn.close()


__all__ = [
    "_ago_minutes",
    "_now_literal",
    "apply_ddl_statements",
    "EVENTS_TABLE_FOR_STALE_DETECTION",
    "conn",
    "ownership_conn",
]
