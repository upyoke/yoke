"""Shared module-level helpers for doctor_filesystem_full test files.

Underscore prefix keeps pytest from collecting this as a test module.
Used by test_doctor_filesystem_full.py and its split siblings.

Non-fixture helpers — plain Python functions invoked directly. The
shared `_make_conn`/`_args`/`_run_hc`/`_cp` helpers consolidate test
scaffolding across split files.
"""

from __future__ import annotations

import subprocess

from yoke_core.engines.doctor import DoctorArgs, RecordCollector
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl


def _make_conn():
    """Create a disposable Postgres DB with minimal schema for filesystem HC testing.

    The backing database is dropped when the connection closes; a
    garbage-collection finalizer covers connections a test never closes.
    """
    from runtime.api.fixtures import pg_testdb

    name = pg_testdb.create_test_database()
    conn = pg_testdb.connect_test_database(name)
    apply_fixture_ddl(
        conn,
        """
        CREATE TABLE items (
            id INTEGER PRIMARY KEY,
            status TEXT,
            spec_updated_at TEXT
        );

        CREATE TABLE projects (
            id INTEGER PRIMARY KEY,
            slug TEXT UNIQUE,
            github_repo TEXT
        );
        """
    )
    return pg_testdb.drop_database_on_close(conn, name)


def _args(**overrides) -> DoctorArgs:
    defaults = dict(file=None, fix=False, only=None, quick=False, project="yoke", db_path=None)
    defaults.update(overrides)
    return DoctorArgs(**defaults)


def _run_hc(fn, conn=None, **kwargs) -> RecordCollector:
    if conn is None:
        conn = _make_conn()
    rec = RecordCollector()
    fn(conn, _args(**kwargs), rec)
    return rec


def _cp(returncode=0, stdout="", stderr="") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess([], returncode, stdout, stderr)
