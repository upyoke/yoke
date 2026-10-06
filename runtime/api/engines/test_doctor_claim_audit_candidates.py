"""Indexed function candidates preserve decoded full-history evidence."""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from uuid import uuid4

from psycopg.conninfo import conninfo_to_dict

import pytest

from yoke_contracts.schema_authority import (
    SchemaAuthorityRefused,
    serving_build_authority,
)
from yoke_core.domain import db_backend
from yoke_core.domain.check_claim_boundary_audit_summary import audit_summary
from yoke_core.domain.events_function_index import (
    BOOTSTRAP_AUDIT_RECORD,
    FUNCTION_INDEX_NAME,
    _connection_dsn,
    ensure_function_index,
    function_lookup_sql,
    verify_function_index,
)
from yoke_core.domain.migration_audit_schema import (
    ensure_migration_audit_table_postgres,
)
from runtime.api.engines.test_doctor_hc_claim_boundary_audit import (
    _add_event,
    _add_session,
    _disable_event_id_cutoff as _disable_event_id_cutoff,
    _sid,
    env as env,
)


@pytest.fixture(autouse=True)
def index_audit_schema(env):
    # The classifier fixture intentionally has no migration machinery.
    conn = env["conn"]
    conn.execute(f"DROP INDEX IF EXISTS {FUNCTION_INDEX_NAME}")
    ensure_migration_audit_table_postgres(conn)
    conn.commit()


def _ensure(conn):
    conn.commit()
    with serving_build_authority():
        ensure_function_index(conn)


def test_secondary_connection_retains_private_credential_and_target(env):
    info = env["conn"].info
    marker = uuid4().hex
    redacted = info.dsn
    copy = _connection_dsn(
        SimpleNamespace(info=SimpleNamespace(dsn=redacted, password=marker))
    )
    parameters = conninfo_to_dict(copy)
    assert parameters["password"] == marker
    assert parameters["dbname"] == info.dbname
    assert parameters["user"] == info.user
    assert "password" not in conninfo_to_dict(redacted)


def test_decoded_identifiers_and_missing_indexed_subject_remain_candidates(env):
    conn = env["conn"]
    caller = _sid("e")
    _add_session(conn, caller)
    # The subject is only in context, so the indexed item column cannot be
    # used to exclude this historical event.
    event_id = _add_event(
        conn,
        "YokeFunctionCalled",
        caller,
        None,
        {"function": "items.structured_field.replace", "target": {"item_id": 910}},
        created_at="2020-01-01T00:00:00Z",
    )
    conn.execute(
        "UPDATE events SET envelope=replace(replace(envelope, 'function', %s), 'items', %s) "
        "WHERE id=%s",
        (r"funct\u0069on", r"\u0069tems", event_id),
    )
    conn.commit()
    _ensure(conn)
    fails, warns, preview = audit_summary(conn)
    assert (fails, warns) == (0, 1)
    assert preview[0]["id"] == event_id
    assert preview[0]["item_id"] == 910


def test_index_handles_escaped_nul_and_ignores_unrelated_large_context(env):
    conn = env["conn"]
    caller = _sid("f")
    _add_session(conn, caller)
    _add_event(
        conn,
        "YokeFunctionCalled",
        caller,
        911,
        {"function": "items.structured_field.replace", "irrelevant": "\x00"},
    )
    _add_event(
        conn,
        "YokeFunctionCalled",
        caller,
        911,
        {
            "function": "health.read",
            "irrelevant": "items.structured_field.replace" * 20000,
        },
    )
    _add_event(
        conn,
        "YokeFunctionCalled",
        caller,
        911,
        {"function": "unrelated" * 10000},
    )
    _add_event(
        conn,
        "YokeFunctionCalled",
        caller,
        911,
        {
            "function": "items.structured_field." + "unknown" * 1000,
            "side_effects": ["change"],
            "claim_required_kind": "item",
        },
    )
    _ensure(conn)
    assert audit_summary(conn)[:2] == (0, 2)
    verify_function_index(conn)


def test_index_lookup_and_repeated_boot_receipt(env):
    conn = env["conn"]
    conn.execute(
        """
        INSERT INTO events (event_id, source_type, session_id, severity, event_kind,
                            event_type, event_name, envelope, created_at)
        SELECT 'unrelated-' || n, 'backend', 'caller', 'INFO', 'lifecycle',
               'function_call', 'YokeFunctionCalled', %s, '2020-01-01T00:00:00Z'
        FROM generate_series(1, 5000) n
        """,
        (json.dumps({"context": {"function": "health.read"}}),),
    )
    _ensure(conn)
    conn.execute("ANALYZE events")
    plan = conn.execute(
        f"EXPLAIN SELECT id FROM events WHERE event_name='YokeFunctionCalled' "
        f"AND ({function_lookup_sql()} LIKE %s OR {function_lookup_sql()}=%s)",
        ("items.%", "items"),
    ).fetchall()
    assert FUNCTION_INDEX_NAME in "\n".join(row[0] for row in plan)
    conn.commit()
    _ensure(conn)
    receipts = conn.execute(
        "SELECT count(*) FROM migration_audit WHERE migration_name=%s "
        "AND state='completed'",
        (BOOTSTRAP_AUDIT_RECORD["name"],),
    ).fetchone()[0]
    assert receipts == 1


def test_bootstrap_audit_row_matches_shared_declaration(env):
    conn = env["conn"]
    _ensure(conn)
    rows = conn.execute(
        "SELECT migration_name, description, exception_reason, tables_declared, "
        "pre_row_counts, post_row_counts, backup_path FROM migration_audit"
    ).fetchall()
    assert len(rows) == 1
    row = rows[0]
    recorded = dict(
        zip(
            (
                "name",
                "description",
                "exception_reason",
                "tables",
                "pre_counts",
                "post_counts",
            ),
            row[:6],
            strict=True,
        )
    )
    for field in ("tables", "pre_counts", "post_counts"):
        recorded[field] = json.loads(recorded[field])
    # The audit helper represents the explicit no-backup declaration as an
    # empty stored path, rather than persisting the helper's reason argument.
    assert row[6] == ""
    recorded["backup_reason"] = None
    assert recorded == BOOTSTRAP_AUDIT_RECORD


def test_concurrent_builder_uses_own_autocommit_connection(env, monkeypatch):
    conn = env["conn"]
    conn.commit()
    original = db_backend.connect_psycopg
    observed = []

    class ObserveBuild:
        def __init__(self, inner):
            self.inner = inner

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.inner.close()

        def execute(self, statement, params=None):
            if statement.startswith("CREATE INDEX CONCURRENTLY"):
                observed.append(self.inner.autocommit)
                # Both DDL and this independent writer use the actual target,
                # without changing the caller's transaction mode.
                with original(_connection_dsn(conn), autocommit=True) as writer:
                    writer.execute("SET lock_timeout='1s'")
                    writer.execute(
                        "INSERT INTO events (event_id, source_type, session_id, severity, "
                        "event_kind, event_type, event_name, created_at) VALUES "
                        "('during-build', 'backend', 'caller', 'INFO', 'lifecycle', "
                        "'function_call', 'YokeFunctionCalled', '2020-01-01T00:00:00Z')"
                    )
            return self.inner.execute(statement, params)

    monkeypatch.setattr(
        db_backend, "connect_psycopg", lambda *a, **kw: ObserveBuild(original(*a, **kw))
    )
    with serving_build_authority():
        ensure_function_index(conn)
    assert observed == [True]
    assert not conn.autocommit
    assert conn.execute("SELECT 1 FROM events WHERE event_id='during-build'").fetchone()


def test_production_builder_refuses_without_serving_authority(env, monkeypatch):
    from yoke_core.domain import administered_postgres

    monkeypatch.setattr(
        administered_postgres, "administering_target", lambda **kw: "prod-db-admin"
    )
    with pytest.raises(SchemaAuthorityRefused):
        ensure_function_index(env["conn"])


def test_event_insert_succeeds_while_concurrent_build_waits_for_writer(env):
    conn = env["conn"]
    conn.commit()
    statement = (
        "INSERT INTO events (event_id, source_type, session_id, severity, "
        "event_kind, event_type, event_name, created_at) VALUES "
        "(%s, 'backend', 'caller', 'INFO', 'lifecycle', 'function_call', "
        "'YokeFunctionCalled', '2020-01-01T00:00:00Z')"
    )
    # Hold a writer transaction so the concurrent build stays observable.
    with db_backend.connect_psycopg(_connection_dsn(conn)) as held_writer:
        held_writer.execute(statement, ("held-writer",))
        with ThreadPoolExecutor(max_workers=1) as pool:
            build = pool.submit(_ensure, conn)
            try:
                with db_backend.connect_psycopg(
                    _connection_dsn(conn), autocommit=True
                ) as writer:
                    deadline = time.monotonic() + 5
                    while not writer.execute(
                        "SELECT 1 FROM pg_stat_progress_create_index "
                        "WHERE relid='events'::regclass"
                    ).fetchone():
                        assert time.monotonic() < deadline, (
                            "concurrent build never started"
                        )
                        time.sleep(0.02)
                    writer.execute("SET lock_timeout='1s'")
                    writer.execute(statement, ("during-concurrent-build",))
            finally:
                held_writer.commit()
                build.result(timeout=10)
    verify_function_index(conn)
