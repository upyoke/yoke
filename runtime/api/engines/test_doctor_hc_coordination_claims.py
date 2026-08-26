"""Tests for the coordination-claim doctor health checks."""

from __future__ import annotations

import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import pytest

from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
from yoke_core.engines.doctor_hc_coordination_claims import (
    hc_coordination_claims_stale_or_orphan,
    hc_coordination_claims_unmerged_source,
)
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


_CLAIMS_DDL = """
CREATE TABLE work_claims (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id TEXT NOT NULL,
    target_kind TEXT NOT NULL,
    scope TEXT NOT NULL,
    claim_type TEXT NOT NULL DEFAULT 'exclusive',
    claimed_at TEXT NOT NULL,
    last_heartbeat TEXT,
    released_at TEXT,
    release_reason TEXT,
    release_reason_intent TEXT
);
CREATE TABLE harness_sessions (
    session_id TEXT PRIMARY KEY,
    ended_at TEXT
);
"""


def _insert_claim(conn, **kwargs) -> None:
    """Insert one coordination claim row directly, no domain layer."""
    conn.execute(
        "INSERT INTO work_claims "
        "(session_id, target_kind, scope, claimed_at, last_heartbeat, "
        "released_at, release_reason) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (
            kwargs["session_id"],
            kwargs.get("target_kind", "qa_admission"),
            kwargs.get("scope", '{"machine_id":"mac-mini-lab"}'),
            kwargs["claimed_at"],
            kwargs.get("last_heartbeat"),
            kwargs.get("released_at"),
            kwargs.get("release_reason"),
        ),
    )
    conn.commit()

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
def claims_conn():
    c = _make_conn(_CLAIMS_DDL)
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
    hc_coordination_claims_stale_or_orphan(conn, DoctorArgs(), rec)
    return rec


def _run_unmerged(conn) -> RecordCollector:
    rec = RecordCollector()
    hc_coordination_claims_unmerged_source(conn, DoctorArgs(), rec)
    return rec


class TestStaleOrOrphan:
    def test_pass_when_no_claims(self, claims_conn) -> None:
        rec = _run_stale(claims_conn)
        assert rec.results[-1].result == "PASS"

    def test_pass_for_fresh_heartbeat(self, claims_conn) -> None:
        _insert_claim(
            claims_conn,
            session_id="sess-fresh",
            claimed_at=_iso_ago(minutes=1),
            last_heartbeat=_iso_ago(minutes=1),
        )
        rec = _run_stale(claims_conn)
        assert rec.results[-1].result == "PASS"

    def test_warn_for_stale_heartbeat(self, claims_conn) -> None:
        _insert_claim(
            claims_conn,
            session_id="sess-stale",
            claimed_at=_iso_ago(days=1),
            last_heartbeat=_iso_ago(minutes=120),
        )
        rec = _run_stale(claims_conn)
        result = rec.results[-1]
        assert result.result == "WARN"
        assert "stale" in result.detail.lower() or "orphan" in result.detail.lower()
        assert "sess-stale" in result.detail
        assert "QA_HOST:mac-mini-lab" in result.detail
        assert "yoke coordination-claim release" in result.detail

    def test_warn_for_orphan_when_session_ended(self, claims_conn) -> None:
        claims_conn.execute(
            "INSERT INTO harness_sessions (session_id, ended_at) VALUES (%s, %s)",
            ("sess-ended", _iso_ago(minutes=0)),
        )
        _insert_claim(
            claims_conn,
            session_id="sess-ended",
            claimed_at=_iso_ago(minutes=1),
            last_heartbeat=_iso_ago(minutes=1),
        )
        rec = _run_stale(claims_conn)
        assert rec.results[-1].result == "WARN"
        assert "sess-ended" in rec.results[-1].detail

    def test_item_owned_territory_is_excluded(self, claims_conn) -> None:
        """No session liveness applies, so an old heartbeat is not a signal."""
        _insert_claim(
            claims_conn,
            session_id="rehearse-old",
            target_kind="migration_serialization",
            scope='{"item_id":7,"model":"primary","project_id":1}',
            claimed_at=_iso_ago(days=1),
            last_heartbeat=_iso_ago(minutes=120),
        )
        rec = _run_stale(claims_conn)
        assert rec.results[-1].result == "PASS"

    def test_backlog_claims_are_excluded(self, claims_conn) -> None:
        """This check owns shared resources, not backlog occupancy."""
        _insert_claim(
            claims_conn,
            session_id="sess-item",
            target_kind="item",
            scope='{"item_id":7}',
            claimed_at=_iso_ago(days=1),
            last_heartbeat=_iso_ago(minutes=120),
        )
        rec = _run_stale(claims_conn)
        assert rec.results[-1].result == "PASS"

    def test_released_claims_excluded(self, claims_conn) -> None:
        _insert_claim(
            claims_conn,
            session_id="sess-done",
            claimed_at=_iso_ago(days=1),
            last_heartbeat=_iso_ago(days=1),
            released_at=_iso_ago(minutes=0),
            release_reason="completed",
        )
        rec = _run_stale(claims_conn)
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
            "CREATE TABLE work_claims (id INTEGER PRIMARY KEY, "
            "session_id TEXT, target_kind TEXT, scope TEXT, "
            "claimed_at TEXT, released_at TEXT, release_reason TEXT);"
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
