"""Shared constants and row helpers for ``test_events_crud_full*``.

Filename omits the ``test_`` prefix so pytest does not collect it. Each split
file imports the module-level constants, the ``_insert_event_direct`` /
``_setup_severity_config`` / ``_event_count`` row helpers, and the backend-aware
``db_path`` / ``empty_db_path`` fixtures defined here. The CLI/``cmd_*`` tests
drive a factory-routed ``db_path`` token for a disposable per-test Postgres
database; the direct-SQL tests use the shared ``test_db`` fixture
from ``conftest.py``. Sharing the verbose payload builders + fixtures here keeps
the split files thin.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import pytest

from yoke_core.domain.project_seed_test_helpers import seed_project_identities

from runtime.api.conftest import insert_event
from yoke_core.domain import events_crud as ec
from yoke_core.domain.migration_audit_schema import ensure_migration_audit_table
from runtime.api.fixtures.file_test_db import init_test_db


def _iso_offset_days(days: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


_SEVEN_DAYS_AGO = _iso_offset_days(-7)
_THIRTY_DAYS_AGO = _iso_offset_days(-30)


# Synthetic test item ID — not a real backlog item reference.
TEST_ITEM_ID = 4242
TEST_ITEM_REF = f"YOK-{TEST_ITEM_ID}"


def _unique_event_id() -> str:
    return f"evt-{uuid.uuid4().hex[:12]}"


def _insert_event_direct(
    conn: Any,
    *,
    event_id: Optional[str] = None,
    event_name: str = "TestEvent",
    event_kind: str = "lifecycle",
    event_type: str = "test",
    source_type: str = "system",
    session_id: str = "sess-test",
    severity: str = "INFO",
    project: str = "yoke",
    anomaly_flags: Optional[str] = None,
    envelope: Optional[str] = None,
    created_at: Optional[str] = None,
    **kwargs,
) -> Any:
    """Insert an event row directly into the test DB."""
    return insert_event(
        conn,
        event_id=event_id or _unique_event_id(),
        event_name=event_name,
        event_kind=event_kind,
        event_type=event_type,
        source_type=source_type,
        session_id=session_id,
        severity=severity,
        project=project,
        anomaly_flags=anomaly_flags,
        envelope=envelope,
        created_at=created_at,
        **kwargs,
    )


def _setup_severity_config(conn: Any) -> None:
    """Insert default severity_config row."""
    conn.execute(
        "INSERT INTO severity_config "
        "(event_name, source_type, min_severity, created_at) "
        "VALUES ('*', '*', 'INFO', '2026-01-01T00:00:00Z') "
        "ON CONFLICT DO NOTHING"
    )
    conn.commit()


def _event_count(conn: Any) -> int:
    return conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]


def _apply_events_full_schema() -> None:
    """``apply_schema`` strategy for the ``db_path`` fixture.

    Bootstraps ``migration_audit`` (canonical DDL — ``cmd_prune`` writes an audit
    fingerprint through the exception pathway) then runs ``events_crud.cmd_init``
    against the repointed ``YOKE_PG_DSN``. Test bodies assert table presence
    through ``schema_common`` rather than SQLite catalog probes, so no
    introspection shim is needed.
    """
    from yoke_core.domain import db_backend

    conn = db_backend.connect()
    try:
        ensure_migration_audit_table(conn)
    finally:
        conn.close()
    ec.cmd_init()
    conn = db_backend.connect()
    try:
        seed_project_identities(conn)
    finally:
        conn.close()
    conn = db_backend.connect()
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
            (TEST_ITEM_ID, TEST_ITEM_ID),
        )
        conn.commit()
    finally:
        conn.close()


def _apply_empty_schema() -> None:
    """``apply_schema`` strategy yielding a DB with NO events schema.

    ``cmd_registry_audit`` / ``cmd_registry_diff`` now use native schema
    helpers for missing-table guards, so this intentionally does nothing.
    """


@pytest.fixture
def db_path(tmp_path):
    """Backend-aware fresh DB with events tables + migration_audit; yields path.

    Creates a disposable per-test database with ``YOKE_PG_DSN`` repointed and
    dropped on teardown, so factory-routed events_crud calls land in an isolated
    DB across tests.
    """
    with init_test_db(tmp_path, apply_schema=_apply_events_full_schema) as path:
        yield path


@pytest.fixture
def empty_db_path(tmp_path):
    """Backend-aware DB with no events schema; yields path.

    Drives the missing-table error paths in ``cmd_registry_audit`` /
    ``cmd_registry_diff`` using a disposable Postgres database with no events
    schema.
    """
    with init_test_db(tmp_path, apply_schema=_apply_empty_schema) as path:
        yield path


__all__ = [
    "_iso_offset_days",
    "_SEVEN_DAYS_AGO",
    "_THIRTY_DAYS_AGO",
    "TEST_ITEM_ID",
    "TEST_ITEM_REF",
    "_unique_event_id",
    "_insert_event_direct",
    "_setup_severity_config",
    "_event_count",
    "db_path",
    "empty_db_path",
]
