"""Shared DDL, fixture, and helpers for events_crud test sibling modules."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from yoke_core.domain import events_crud as ec
from yoke_core.domain.migration_audit_schema import ensure_migration_audit_table
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


def _iso_offset_days(days: int) -> str:
    """Return an ISO-8601 UTC timestamp ``days`` in the past (or future)."""
    return (datetime.now(timezone.utc) + timedelta(days=days)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _apply_events_schema() -> None:
    """``apply_schema`` strategy for the events_crud test fixtures.

    Applies the canonical ``migration_audit`` DDL (the exception-pathway helper
    writes into it) plus ``events_crud.cmd_init`` against the disposable
    per-test Postgres database. Test bodies assert schema through
    ``schema_common`` rather than SQLite catalog probes, so no introspection
    shim is needed.
    """
    from yoke_core.domain import db_backend

    conn = db_backend.connect()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY,
                slug TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                public_item_prefix TEXT NOT NULL DEFAULT 'YOK'
            )
            """
        )
        p = "%s" if db_backend.connection_is_postgres(conn) else "?"
        conn.execute(
            "INSERT INTO projects (id, slug, name, public_item_prefix) "
            f"VALUES ({p}, {p}, {p}, {p}) "
            "ON CONFLICT (id) DO NOTHING",
            (1, "yoke", "Yoke", "YOK"),
        )
        conn.commit()
        ensure_migration_audit_table(conn)
    finally:
        conn.close()
    ec.cmd_init()


@pytest.fixture
def db_path(tmp_path: Path):
    """Backend-aware fresh DB with events tables + migration_audit; yields path.

    ``YOKE_PG_DSN`` is repointed to a disposable per-test Postgres database
    and restored on teardown, so factory-routed events_crud calls land in an
    isolated DB across tests.
    """
    with init_test_db(tmp_path, apply_schema=_apply_events_schema) as path:
        yield path


def _insert_event(db_path: str, **overrides) -> None:
    """Insert a test event with sensible defaults."""
    defaults = dict(
        event_id="evt-001",
        source_type="agent",
        session_id="sess-001",
        event_kind="system",
        event_type="tool_call",
        event_name="HarnessToolCallCompleted",
        severity="INFO",
        skip_severity=True,
    )
    defaults.update(overrides)
    _ensure_item_row(db_path, defaults.get("item_id"))
    ec.cmd_insert(db_path, **defaults)


def _ensure_item_row(db_path: str, item_id) -> None:
    if item_id is None:
        return
    text = str(item_id).removeprefix("YOK-").removeprefix("yok-")
    if not text.isdigit():
        return
    numeric = int(text)
    conn = connect_test_db(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS items (
                id INTEGER PRIMARY KEY,
                project_id INTEGER NOT NULL REFERENCES projects(id),
                project_sequence INTEGER NOT NULL,
                UNIQUE(project_id, project_sequence)
            )
            """
        )
        conn.execute(
            "INSERT INTO items (id, project_id, project_sequence) "
            "VALUES (%s, 1, %s) ON CONFLICT(id) DO NOTHING",
            (numeric, numeric),
        )
        conn.commit()
    finally:
        conn.close()
