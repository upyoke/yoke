"""Tests for HC-path-integrity."""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain import db_backend
from yoke_core.engines.doctor_hc_path_integrity import (
    hc_path_integrity,
)
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl


_SCHEMA = """
CREATE TABLE projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE path_integrity_runs (
    id INTEGER PRIMARY KEY,
    project_id TEXT NOT NULL,
    commit_sha TEXT,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    skip_reason TEXT,
    block_reason TEXT,
    abort_reason TEXT,
    failure_count INTEGER NOT NULL DEFAULT 0,
    unrepaired_failure_count INTEGER NOT NULL DEFAULT 0,
    verifier_version TEXT NOT NULL DEFAULT 'v1'
);
"""


def _apply_path_integrity_schema() -> None:
    conn = db_backend.connect()
    try:
        apply_fixture_ddl(conn, _SCHEMA)
    finally:
        conn.close()


@pytest.fixture
def conn(tmp_path: Path):
    with init_test_db(tmp_path, apply_schema=_apply_path_integrity_schema) as db_path:
        c = connect_test_db(db_path)
        try:
            c.execute(
                "INSERT INTO projects (id, name, created_at) VALUES "
                "('alpha', 'alpha', '2026-04-30')"
            )
            c.execute(
                "INSERT INTO projects (id, name, created_at) VALUES "
                "('beta', 'beta', '2026-04-30')"
            )
            c.commit()
            yield c
        finally:
            c.close()


def _run_hc(conn) -> RecordCollector:
    rec = RecordCollector()
    args = DoctorArgs()
    hc_path_integrity(conn, args, rec)
    return rec


def _insert_run(conn, *, project_id, status, unrepaired=0, run_id=None):
    if run_id is None:
        cur = conn.execute(
            "INSERT INTO path_integrity_runs "
            "(project_id, commit_sha, status, started_at, "
            " unrepaired_failure_count) "
            "VALUES (%s, 'shaA', %s, '2026-04-30T00:00:00Z', %s) "
            "RETURNING id",
            (project_id, status, unrepaired),
        )
    else:
        cur = conn.execute(
            "INSERT INTO path_integrity_runs "
            "(id, project_id, commit_sha, status, started_at, "
            " unrepaired_failure_count) "
            "VALUES (%s, %s, 'shaA', %s, '2026-04-30T00:00:00Z', %s) "
            "RETURNING id",
            (run_id, project_id, status, unrepaired),
        )
    conn.commit()
    return int(cur.fetchone()[0])


def test_pass_when_all_runs_pass(conn):
    _insert_run(conn, project_id="alpha", status="passed")
    _insert_run(conn, project_id="beta", status="passed")
    rec = _run_hc(conn)
    assert rec.results[0].result == "PASS"


def test_warn_on_failed_latest_run(conn):
    _insert_run(conn, project_id="alpha", status="passed")
    _insert_run(conn, project_id="beta", status="failed", unrepaired=2)
    rec = _run_hc(conn)
    assert rec.results[0].result == "WARN"
    assert "beta" in rec.results[0].detail
    assert "unrepaired_failures=2" in rec.results[0].detail


def test_warn_on_stale_running_run(conn):
    _insert_run(conn, project_id="alpha", status="running")
    rec = _run_hc(conn)
    assert rec.results[0].result == "WARN"
    assert "stale_running" in rec.results[0].detail


def test_pass_with_skipped_projects(conn):
    _insert_run(conn, project_id="alpha", status="skipped")
    _insert_run(conn, project_id="beta", status="passed")
    rec = _run_hc(conn)
    assert rec.results[0].result == "PASS"
    assert "skipped" in rec.results[0].detail


def test_passes_when_table_missing(tmp_path: Path):
    # Simulate a DB that has no path_integrity_runs table at all
    def apply_schema() -> None:
        seeded = db_backend.connect()
        try:
            seeded.execute(
                "CREATE TABLE projects ("
                "id TEXT PRIMARY KEY, name TEXT, created_at TEXT)"
            )
            seeded.commit()
        finally:
            seeded.close()

    with init_test_db(tmp_path, apply_schema=apply_schema) as db_path:
        c = connect_test_db(db_path)
        try:
            rec = _run_hc(c)
            assert rec.results[0].result == "PASS"
            assert "table missing" in rec.results[0].detail
        finally:
            c.close()


def test_latest_run_takes_precedence_over_history(conn):
    # First run failed, but the latest run for alpha passed → no WARN
    # provided no unrepaired failures linger.
    _insert_run(conn, project_id="alpha", status="failed", unrepaired=0)
    _insert_run(conn, project_id="alpha", status="passed", unrepaired=0)
    _insert_run(conn, project_id="beta", status="passed")
    rec = _run_hc(conn)
    assert rec.results[0].result == "PASS"
