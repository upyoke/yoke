"""Tests for Postgres disposable test database helpers."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from runtime.api.fixtures import pg_testdb
from yoke_contracts.schema_authority import SchemaAuthorityRefused
from yoke_core.domain import pg_test_db_namespace


def test_setup_ambient_test_db_clones_template_and_registers_cleanup(monkeypatch):
    admin_sql = []
    cleanups = []

    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw3")
    monkeypatch.setattr(pg_testdb, "_base_dsn", lambda: "host=/tmp dbname=postgres")
    monkeypatch.setattr(pg_testdb, "_admin_execute", lambda sql: admin_sql.append(sql))
    monkeypatch.setattr(pg_testdb.atexit, "register", lambda fn: cleanups.append(fn))
    monkeypatch.setattr(pg_testdb, "_fixture_template_db", lambda: "yoke_test_tmpl")

    name = pg_testdb.setup_ambient_test_db()

    # The worker id keeps two workers apart; the run tag keeps two concurrent
    # invocations apart, which is what makes one shared cluster safe.
    assert f"_{pg_testdb.AMBIENT_DB_PURPOSE}_gw3_" in name
    assert pg_test_db_namespace.belongs_to_current_run(name)
    assert admin_sql == [f'CREATE DATABASE "{name}" TEMPLATE "yoke_test_tmpl"']

    cleanups[0]()
    assert admin_sql[-1] == f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'


def test_fixture_template_db_builds_once_then_clones(monkeypatch):
    admin_sql = []
    cleanups = []
    applied = []
    closed = []

    monkeypatch.setattr(pg_testdb, "_base_dsn", lambda: "host=/tmp dbname=postgres")
    monkeypatch.setattr(pg_testdb, "_admin_execute", lambda sql: admin_sql.append(sql))
    monkeypatch.setattr(pg_testdb.atexit, "register", lambda fn: cleanups.append(fn))
    monkeypatch.setattr(pg_testdb, "_apply_schema", lambda conn: applied.append(conn))
    monkeypatch.setattr(
        pg_testdb.db_backend,
        "_open_native_postgres",
        lambda dsn: SimpleNamespace(close=lambda: closed.append(True)),
    )
    monkeypatch.setattr(pg_testdb, "_FIXTURE_TEMPLATE_DB", None)

    template = pg_testdb._fixture_template_db()

    assert template.startswith(pg_testdb.TEST_DB_PREFIX)
    assert pg_test_db_namespace.belongs_to_current_run(template)
    assert admin_sql == [f'CREATE DATABASE "{template}"']
    assert len(applied) == 1
    assert closed == [True]

    # Second call reuses the built template without another apply.
    assert pg_testdb._fixture_template_db() == template
    assert len(applied) == 1

    clone = pg_testdb.create_test_database(template=template)
    assert admin_sql[-1] == f'CREATE DATABASE "{clone}" TEMPLATE "{template}"'

    cleanups[0]()
    assert admin_sql[-1] == f'DROP DATABASE IF EXISTS "{template}" WITH (FORCE)'


def test_fixture_template_schema_refusal_drops_the_created_database(monkeypatch):
    admin_sql = []
    registered = []
    unregistered = []
    closed = []

    monkeypatch.setattr(pg_testdb, "_base_dsn", lambda: "host=/tmp dbname=postgres")
    monkeypatch.setattr(pg_testdb, "_admin_execute", admin_sql.append)
    monkeypatch.setattr(pg_testdb.atexit, "register", registered.append)
    monkeypatch.setattr(pg_testdb.atexit, "unregister", unregistered.append)
    monkeypatch.setattr(
        pg_testdb,
        "_apply_schema",
        lambda _conn: (_ for _ in ()).throw(SchemaAuthorityRefused("refused")),
    )
    monkeypatch.setattr(
        pg_testdb.db_backend,
        "_open_native_postgres",
        lambda _dsn: SimpleNamespace(close=lambda: closed.append(True)),
    )
    monkeypatch.setattr(pg_testdb, "_FIXTURE_TEMPLATE_DB", None)

    with pytest.raises(SchemaAuthorityRefused):
        pg_testdb._fixture_template_db()

    name = admin_sql[0].split('"')[1]
    assert admin_sql == [
        f'CREATE DATABASE "{name}"',
        f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)',
    ]
    assert closed == [True]
    assert unregistered == registered
    assert pg_testdb._FIXTURE_TEMPLATE_DB is None


def test_refuses_to_drop_another_invocations_database(monkeypatch):
    """The guard that makes concurrent runs safe without coordinating.

    A run may only ever drop what it created. Reclaiming what an interrupted
    run left behind belongs to the ownership-gated orphan sweep, which first
    checks that the owning process has actually exited.
    """
    dropped = []
    monkeypatch.setattr(pg_testdb, "_base_dsn", lambda: "host=/tmp dbname=postgres")
    monkeypatch.setattr(pg_testdb, "_admin_execute", lambda sql: dropped.append(sql))
    theirs = (
        f"{pg_testdb.TEST_DB_PREFIX}{pg_test_db_namespace.mint_run_tag(pid=31337)}_abc"
    )

    with pytest.raises(RuntimeError, match="another invocation"):
        pg_testdb.drop_test_database(theirs)

    assert dropped == []


def test_refuses_to_operate_on_a_non_test_database():
    with pytest.raises(RuntimeError, match="non-test database"):
        pg_testdb.drop_test_database("production")
