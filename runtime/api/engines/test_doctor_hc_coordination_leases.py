"""Tests for the coordination-lease doctor health checks."""

from __future__ import annotations

import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import pytest

from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
from yoke_core.engines.doctor_hc_coordination_leases import (
    hc_coordination_leases_stale_or_orphan,
    hc_coordination_leases_unmerged_source,
)
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


_LEASES_DDL = """
CREATE TABLE coordination_leases (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    project_id TEXT NOT NULL,
    lease_key TEXT NOT NULL,
    session_id TEXT NOT NULL,
    actor_id TEXT,
    acquired_at TEXT NOT NULL,
    heartbeat_at TEXT,
    released_at TEXT,
    release_reason TEXT
);
CREATE TABLE harness_sessions (
    session_id TEXT PRIMARY KEY,
    ended_at TEXT
);
"""

_AUDIT_DDL = """
CREATE TABLE migration_audit (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    migration_name TEXT NOT NULL,
    state TEXT NOT NULL,
    source_branch TEXT,
    source_commit TEXT,
    integration_target TEXT,
    worktree TEXT,
    completed_at TEXT
);
"""


def _make_conn(ddl: Optional[str] = None):
    name = pg_testdb.create_test_database()
    c = pg_testdb.drop_database_on_close(
        pg_testdb.connect_test_database(name), name
    )
    if ddl:
        apply_fixture_ddl(c, ddl)
    return c


@pytest.fixture
def leases_conn():
    c = _make_conn(_LEASES_DDL)
    yield c
    c.close()


@pytest.fixture
def audit_conn():
    c = _make_conn(_AUDIT_DDL)
    yield c
    c.close()


def _iso_ago(*, minutes: int = 0, days: int = 0) -> str:
    moment = datetime.now(timezone.utc) - timedelta(minutes=minutes, days=days)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _run_stale(conn) -> RecordCollector:
    rec = RecordCollector()
    hc_coordination_leases_stale_or_orphan(conn, DoctorArgs(), rec)
    return rec


def _run_unmerged(conn) -> RecordCollector:
    rec = RecordCollector()
    hc_coordination_leases_unmerged_source(conn, DoctorArgs(), rec)
    return rec


class TestStaleOrOrphan:
    def test_pass_when_no_leases(self, leases_conn) -> None:
        rec = _run_stale(leases_conn)
        assert rec.results[-1].result == "PASS"

    def test_pass_for_fresh_heartbeat(self, leases_conn) -> None:
        leases_conn.execute(
            "INSERT INTO coordination_leases "
            "(project_id, lease_key, session_id, acquired_at, heartbeat_at) "
            "VALUES (%s, %s, %s, %s, %s)",
            ("yoke", "LIVE_DB_MIGRATION:primary", "sess-fresh",
             _iso_ago(minutes=1), _iso_ago(minutes=1)),
        )
        leases_conn.commit()
        rec = _run_stale(leases_conn)
        assert rec.results[-1].result == "PASS"

    def test_warn_for_stale_heartbeat(self, leases_conn) -> None:
        leases_conn.execute(
            "INSERT INTO coordination_leases "
            "(project_id, lease_key, session_id, acquired_at, heartbeat_at) "
            "VALUES (%s, %s, %s, %s, %s)",
            ("yoke", "LIVE_DB_MIGRATION:primary", "sess-stale",
             _iso_ago(days=1), _iso_ago(minutes=120)),
        )
        leases_conn.commit()
        rec = _run_stale(leases_conn)
        result = rec.results[-1]
        assert result.result == "WARN"
        assert "stale" in result.detail.lower() or "orphan" in result.detail.lower()
        assert "sess-stale" in result.detail

    def test_warn_for_orphan_when_session_ended(self, leases_conn) -> None:
        now = _iso_ago(minutes=0)
        leases_conn.execute(
            "INSERT INTO harness_sessions (session_id, ended_at) VALUES (%s, %s)",
            ("sess-ended", now),
        )
        leases_conn.execute(
            "INSERT INTO coordination_leases "
            "(project_id, lease_key, session_id, acquired_at, heartbeat_at) "
            "VALUES (%s, %s, %s, %s, %s)",
            ("yoke", "LIVE_DB_MIGRATION:primary", "sess-ended",
             _iso_ago(minutes=1), _iso_ago(minutes=1)),
        )
        leases_conn.commit()
        rec = _run_stale(leases_conn)
        assert rec.results[-1].result == "WARN"
        assert "sess-ended" in rec.results[-1].detail

    def test_released_leases_excluded(self, leases_conn) -> None:
        leases_conn.execute(
            "INSERT INTO coordination_leases "
            "(project_id, lease_key, session_id, acquired_at, heartbeat_at, "
            " released_at, release_reason) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            ("yoke", "LIVE_DB_MIGRATION:primary", "sess-done",
             _iso_ago(days=1), _iso_ago(days=1),
             _iso_ago(minutes=0), "completed"),
        )
        leases_conn.commit()
        rec = _run_stale(leases_conn)
        assert rec.results[-1].result == "PASS"

    def test_skip_when_table_missing(self) -> None:
        conn = _make_conn()
        try:
            rec = _run_stale(conn)
            assert rec.results[-1].result == "PASS"
            assert "skipping" in rec.results[-1].detail.lower()
        finally:
            conn.close()

    def test_skip_when_heartbeat_column_missing(self) -> None:
        conn = _make_conn(
            "CREATE TABLE coordination_leases (id INTEGER PRIMARY KEY, "
            "project_id TEXT, lease_key TEXT, session_id TEXT, "
            "acquired_at TEXT, released_at TEXT, release_reason TEXT);"
        )
        try:
            rec = _run_stale(conn)
            assert rec.results[-1].result == "PASS"
        finally:
            conn.close()


class TestUnmergedSource:
    def test_pass_when_no_audit_rows(self, audit_conn) -> None:
        rec = _run_unmerged(audit_conn)
        assert rec.results[-1].result == "PASS"

    def test_pass_when_columns_missing(self) -> None:
        conn = _make_conn(
            "CREATE TABLE migration_audit (id INTEGER PRIMARY KEY, "
            "migration_name TEXT, state TEXT);"
        )
        try:
            rec = _run_unmerged(conn)
            assert rec.results[-1].result == "PASS"
        finally:
            conn.close()

    def test_pass_when_branch_missing_treats_as_merged(self, audit_conn) -> None:
        # source_branch IS NULL → excluded by WHERE source_branch IS NOT NULL
        audit_conn.execute(
            "INSERT INTO migration_audit "
            "(migration_name, state, source_branch, integration_target, worktree) "
            "VALUES (%s, %s, %s, %s, %s)",
            ("mod_a", "completed", None, "main", "/nonexistent"),
        )
        audit_conn.commit()
        rec = _run_unmerged(audit_conn)
        assert rec.results[-1].result == "PASS"

    def test_pass_when_worktree_unreachable(self, audit_conn) -> None:
        # _branch_merged returns True on git failure (best-effort).
        audit_conn.execute(
            "INSERT INTO migration_audit "
            "(migration_name, state, source_branch, integration_target, worktree) "
            "VALUES (%s, %s, %s, %s, %s)",
            ("mod_a", "completed", "feature-x", "main", "/no/such/path"),
        )
        audit_conn.commit()
        rec = _run_unmerged(audit_conn)
        assert rec.results[-1].result == "PASS"

    def test_warns_when_source_commit_not_on_target(
        self, audit_conn, tmp_path: Path,
    ) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=repo, check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Yoke Test"],
            cwd=repo, check=True,
        )
        (repo / "file.txt").write_text("main\n")
        subprocess.run(["git", "add", "file.txt"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-m", "main"], cwd=repo, check=True)
        subprocess.run(["git", "checkout", "-b", "feature"], cwd=repo, check=True)
        (repo / "file.txt").write_text("feature\n")
        subprocess.run(["git", "commit", "-am", "feature"], cwd=repo, check=True)
        source_commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=repo, text=True,
        ).strip()
        subprocess.run(["git", "checkout", "main"], cwd=repo, check=True)
        subprocess.run(["git", "branch", "-D", "feature"], cwd=repo, check=True)

        audit_conn.execute(
            "INSERT INTO migration_audit "
            "(migration_name, state, source_branch, source_commit, "
            "integration_target, worktree) VALUES (%s, %s, %s, %s, %s, %s)",
            ("mod_a", "completed", "feature", source_commit, "main", str(repo)),
        )
        audit_conn.commit()

        rec = _run_unmerged(audit_conn)
        result = rec.results[-1]
        assert result.result == "WARN"
        assert "mod_a" in result.detail
