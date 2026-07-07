"""Regression coverage for the ``cmd_prune`` audit-fingerprint contract.

``cmd_init`` is a create-only idempotent initializer; the legacy
schema-rebuild path that used to live here is permanently retired —
see ``docs/archive/decisions/events-schema-rebuild-deletion.md``.
What remains in this file is the ``cmd_prune`` audit-fingerprint
contract, which stays durable under the documented retention-only
exception pathway.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from yoke_core.domain import db_backend, events_crud
from yoke_core.domain.migration_audit_schema import ensure_migration_audit_table
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


def _apply_events_and_migration_audit_schema() -> None:
    """``apply_schema`` strategy: events schema (``cmd_init``) + ``migration_audit``.

    ``cmd_prune`` writes events, prunes, and records the ``migration_audit``
    fingerprint all through the backend factory (the DSN on Postgres), so both
    the events table and the audit table must live in the one per-test DB
    ``init_test_db`` provisions. ``cmd_init`` (no-arg) routes through the factory;
    ``migration_audit`` is created on the same factory connection so the
    fingerprint write and readback share that DB on both engines.
    """
    from yoke_core.domain import db_backend
    from yoke_core.domain.events_schema import cmd_init

    cmd_init()
    conn = db_backend.connect()
    try:
        ensure_migration_audit_table(conn)
    finally:
        conn.close()


def test_cmd_prune_emits_audit_fingerprint(tmp_path: Path) -> None:
    """cmd_prune must record a migration_audit fingerprint after a real prune."""
    with init_test_db(
        tmp_path, apply_schema=_apply_events_and_migration_audit_schema
    ) as db_path:
        now = datetime.now(timezone.utc)
        old_ts = (now - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
        new_ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        conn = connect_test_db(db_path)
        try:
            conn.execute(
                "INSERT INTO events (event_id, source_type, session_id, severity, "
                "event_kind, event_type, event_name, created_at) "
                "VALUES ('old-debug', 'agent', 's', 'DEBUG', 'system', 'test', "
                "'Old', %s)",
                (old_ts,),
            )
            conn.execute(
                "INSERT INTO events (event_id, source_type, session_id, severity, "
                "event_kind, event_type, event_name, created_at) "
                "VALUES ('new-info', 'agent', 's', 'INFO', 'system', 'test', "
                "'New', %s)",
                (new_ts,),
            )
            conn.commit()
        finally:
            conn.close()

        events_crud.cmd_prune(str(db_path), dry_run=False)

        conn = connect_test_db(db_path)
        try:
            row = conn.execute(
                "SELECT migration_name, state, exception_reason, pre_row_counts, "
                "post_row_counts FROM migration_audit "
                "WHERE migration_name = 'events-prune' "
                "ORDER BY id DESC LIMIT 1"
            ).fetchone()
        finally:
            conn.close()

        assert row is not None
        assert row[0] == "events-prune"
        assert row[1] == "completed"
        assert row[2] and "retention" in row[2].lower()
        pre = json.loads(row[3])["events"]
        post = json.loads(row[4])["events"]
        assert pre == 2
        assert post == 1


def test_cmd_prune_dry_run_no_fingerprint(tmp_path: Path) -> None:
    """Dry runs must not emit an audit fingerprint."""
    with init_test_db(tmp_path, apply_schema=events_crud.cmd_init) as db_path:
        events_crud.cmd_prune(str(db_path), dry_run=True)

        conn = connect_test_db(db_path)
        try:
            try:
                row = conn.execute(
                    "SELECT COUNT(*) FROM migration_audit "
                    "WHERE migration_name = 'events-prune'"
                ).fetchone()
            except db_backend.operational_error_types(conn):
                row = (0,)
            assert row[0] == 0
        finally:
            conn.close()
