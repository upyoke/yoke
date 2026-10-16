"""Project-or-org scope converges without rewriting existing session work."""

from __future__ import annotations

import importlib
import sqlite3
from contextlib import closing

import psycopg
import pytest

from yoke_core.domain import schema_readiness, session_control_schema
from yoke_core.domain.migration_serving_version import (
    NEXT_RELEASE,
    declared_minimum,
    recorded_floor,
)
from yoke_core.domain.migration_yoke_ledger import YOKE_LEDGER_CONTRACT
from yoke_core.domain.schema_common import _get_columns_with_types
from yoke_core.domain.schema_expected_catalog import parse_expected_schema
from yoke_core.domain.schema_init_tables_sessions import create_session_tables

ENTRY_NAME = "0078_project_optional_sessions"
entry = importlib.import_module(f"yoke_core.domain.migrations.{ENTRY_NAME}")


@pytest.fixture
def scoped_rows(test_db):
    conn = test_db
    org = conn.execute("SELECT id FROM organizations LIMIT 1").fetchone()[0]
    project = conn.execute("SELECT id FROM projects LIMIT 1").fetchone()[0]
    actor = conn.execute("SELECT min(id) FROM actors").fetchone()[0]
    conn.execute(
        "INSERT INTO harness_sessions(session_id,executor,provider,workspace,"
        "project_id,offered_at,last_heartbeat) "
        "VALUES ('scope-session','codex','openai','/scope',%s,now(),now())",
        (project,),
    )
    conn.execute(
        "INSERT INTO session_messages(message_id,body,body_sha256,selector_snapshot,"
        "created_at,expires_at) VALUES ('scope-message','hello','digest','{}',"
        "now(),now()+interval '1 hour')"
    )
    conn.execute(
        "INSERT INTO session_message_recipients(message_id,session_id,project_id,"
        "resolution_evidence,routing_snapshot,created_at,wake_after) "
        "VALUES ('scope-message','scope-session',%s,'{}','{}',now(),now())",
        (project,),
    )
    conn.execute(
        "INSERT INTO session_termination_reaps(target_session_id,project_id,state,"
        "requested_at) VALUES ('scope-session',%s,'pending',now())",
        (project,),
    )
    conn.execute(
        "INSERT INTO session_evidence_fetches(fetch_id,target_session_id,project_id,"
        "machine_id,tail_lines,state,requested_at,requested_by_actor_id) "
        "VALUES ('scope-fetch','scope-session',%s,'machine',20,'pending',now(),%s)",
        (project, actor),
    )
    conn.commit()
    return conn, project, org


def _older_shape(conn):
    for table in entry.TABLES:
        conn.execute(f"ALTER TABLE {table} DROP CONSTRAINT {table}_scope_exactly_one")
        conn.execute(f"DROP INDEX idx_{table}_org")
        conn.execute(f"ALTER TABLE {table} DROP COLUMN org_id")
        conn.execute(f"ALTER TABLE {table} ALTER COLUMN project_id SET NOT NULL")


def _rows(conn):
    return {
        table: [
            row[0]
            for row in conn.execute(f"SELECT to_jsonb(t)-'org_id' FROM {table} t")
        ]
        for table in entry.TABLES
    }


def _tuples(cursor):
    return [tuple(row) for row in cursor]


def _shape(conn):
    return {
        table: (
            dict(_get_columns_with_types(conn, table)),
            _tuples(
                conn.execute(
                    "SELECT column_name,is_nullable FROM information_schema.columns "
                    "WHERE table_schema=current_schema() AND table_name=%s "
                    "AND column_name IN ('project_id','org_id') ORDER BY column_name",
                    (table,),
                )
            ),
            _tuples(
                conn.execute(
                    "SELECT conname,pg_get_constraintdef(oid) FROM pg_constraint "
                    "WHERE conrelid=to_regclass(%s) ORDER BY conname",
                    (table,),
                )
            ),
            _tuples(
                conn.execute(
                    "SELECT indexname,indexdef FROM pg_indexes "
                    "WHERE schemaname=current_schema() AND tablename=%s ORDER BY indexname",
                    (table,),
                )
            ),
        )
        for table in entry.TABLES
    }


def test_migration_preserves_rows_and_adds_org_scope(scoped_rows):
    conn, project, org = scoped_rows
    _older_shape(conn)
    before = _rows(conn)
    entry.apply(conn)
    entry.invariants(conn)
    assert _rows(conn) == before
    for table in entry.TABLES:
        assert conn.execute(f"SELECT project_id,org_id FROM {table}").fetchall() == [
            (project, None)
        ]
        conn.execute(f"UPDATE {table} SET project_id=NULL,org_id=%s", (org,))
    entry.invariants(conn)


def test_migration_is_idempotent(scoped_rows):
    conn, _, _ = scoped_rows
    _older_shape(conn)
    entry.apply(conn)
    before = _shape(conn), _rows(conn)
    entry.apply(conn)
    entry.invariants(conn)
    assert (_shape(conn), _rows(conn)) == before


@pytest.mark.parametrize("table", entry.TABLES)
@pytest.mark.parametrize("both", [True, False], ids=["both", "neither"])
def test_scope_check_rejects_both_and_neither(scoped_rows, table, both):
    conn, project, org = scoped_rows
    _older_shape(conn)
    entry.apply(conn)
    with pytest.raises(psycopg.errors.CheckViolation) as caught:
        with conn.transaction():
            conn.execute(
                f"UPDATE {table} SET project_id=%s,org_id=%s",
                (project if both else None, org if both else None),
            )
    assert caught.value.diag.constraint_name == f"{table}_scope_exactly_one"


@pytest.mark.parametrize("table", entry.TABLES)
def test_org_scope_requires_existing_organization(scoped_rows, table):
    conn, _, _ = scoped_rows
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with conn.transaction():
            conn.execute(f"UPDATE {table} SET project_id=NULL,org_id=-1")


def test_fresh_schema_matches_migrated_schema(scoped_rows):
    conn, _, _ = scoped_rows
    entry.invariants(conn)
    fresh = _shape(conn)
    _older_shape(conn)
    entry.apply(conn)
    entry.invariants(conn)
    assert _shape(conn) == fresh
    catalog = parse_expected_schema()
    for table in entry.TABLES:
        assert catalog[table]["org_id"] == "INTEGER"


def test_additive_boot_precedes_governed_history(scoped_rows):
    conn, _, _ = scoped_rows
    _older_shape(conn)
    create_session_tables(conn)
    session_control_schema.create_session_control_tables(conn)
    entry.apply(conn)
    entry.invariants(conn)


def test_minimum_serving_version_is_next_release():
    assert declared_minimum(entry) == NEXT_RELEASE
    floor = recorded_floor(entry, running_version="9.0.0")
    with closing(sqlite3.connect(":memory:")) as conn:
        conn.execute(
            "CREATE TABLE applied_migrations(migration_name TEXT PRIMARY KEY, "
            "applied_at TEXT,applied_by TEXT,minimum_serving_version TEXT)"
        )
        conn.execute(
            "INSERT INTO applied_migrations VALUES (?, 'now', 'scope-test', ?)",
            (ENTRY_NAME, floor),
        )
        findings = schema_readiness.stranded_by_applied_migrations(
            conn, "8.0.0", (), YOKE_LEDGER_CONTRACT
        )
    assert len(findings) == 1
    assert ENTRY_NAME in findings[0] and "9.0.0" in findings[0]


def test_recipient_table_created_before_attempts_fk(test_db, monkeypatch):
    from yoke_core.domain import session_message_recipient_schema
    from yoke_core.domain.schema_init_apply import (
        execute_schema_script,
        iter_schema_statements,
    )

    statements = []

    def capture(conn, sql):
        statements.extend(iter_schema_statements(sql))
        execute_schema_script(conn, sql)

    monkeypatch.setattr(session_control_schema, "execute_schema_script", capture)
    monkeypatch.setattr(
        session_message_recipient_schema, "execute_schema_script", capture
    )
    test_db.execute("DROP TABLE session_message_attempts")
    test_db.execute("DROP TABLE session_message_recipients")
    session_control_schema.create_session_control_tables(test_db)
    recipient = next(
        i
        for i, sql in enumerate(statements)
        if sql.startswith("CREATE TABLE IF NOT EXISTS session_message_recipients")
    )
    attempts = next(
        i
        for i, sql in enumerate(statements)
        if sql.startswith("CREATE TABLE IF NOT EXISTS session_message_attempts")
    )
    assert recipient < attempts
