"""Tests for Postgres disposable test database helpers."""

from __future__ import annotations

from types import SimpleNamespace

from runtime.api.fixtures import pg_testdb


def test_setup_ambient_test_db_clones_template_and_registers_cleanup(monkeypatch):
    admin_sql = []
    cleanups = []

    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw3")
    monkeypatch.setattr(pg_testdb, "_base_dsn", lambda: "host=/tmp dbname=postgres")
    monkeypatch.setattr(pg_testdb, "_admin_execute", lambda sql: admin_sql.append(sql))
    monkeypatch.setattr(pg_testdb.atexit, "register", lambda fn: cleanups.append(fn))
    monkeypatch.setattr(pg_testdb, "_fixture_template_db", lambda: "yoke_test_tmpl")

    name = pg_testdb.setup_ambient_test_db()

    assert name.startswith("yoke_test_ambient_gw3_")
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
