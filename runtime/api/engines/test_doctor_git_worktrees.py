"""Tests for the doctor engine: worktree, filesystem, and stale-branch HCs.

Git-state HCs (main-checkout, branch-divergence, uncaptured-discoveries,
orphaned-stashes, cross-project-commits) live in test_doctor_git.py.
GitHub-dependent HCs and registration tests live in test_doctor_git_github.py.

Tests use mock subprocess to avoid real git/gh calls.
"""

from __future__ import annotations

import os
import textwrap
import time
from pathlib import Path
from unittest.mock import patch

from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
from yoke_core.engines.doctor import (
    DoctorArgs,
    RecordCollector,
    hc_epic_task_worktree_backfill,
    hc_orphaned_temp_files,
    hc_path_confabulation,
    hc_worktree_health,
)


def _make_conn():
    """Disposable Postgres DB with minimal schema for git/file HC testing."""
    name = pg_testdb.create_test_database()
    conn = pg_testdb.drop_database_on_close(
        pg_testdb.connect_test_database(name), name
    )
    apply_fixture_ddl(conn, textwrap.dedent("""\
        CREATE TABLE items (
            id INTEGER PRIMARY KEY,
            title TEXT,
            type TEXT,
            status TEXT,
            priority TEXT,
            project_id INTEGER DEFAULT 1,
            project_sequence INTEGER,
            github_issue TEXT,
            flow TEXT,
            rework_count INTEGER,
            deployed_to TEXT,
            updated_at TEXT,
            worktree TEXT,
            deployment_flow TEXT
        );

        CREATE TABLE epic_tasks (
            epic_id INTEGER,
            task_num INTEGER,
            title TEXT,
            status TEXT,
            last_heartbeat TEXT,
            dispatch_attempts INTEGER DEFAULT 0,
            worktree TEXT,
            github_issue TEXT,
            PRIMARY KEY (epic_id, task_num)
        );

        CREATE TABLE projects (
            id INTEGER PRIMARY KEY,
            slug TEXT UNIQUE,
            name TEXT,
            default_branch TEXT,
            created_at TEXT,
            github_repo TEXT,
            public_item_prefix TEXT DEFAULT 'YOK'
        );
        INSERT INTO projects
            (id, slug, name, default_branch, created_at,
             github_repo, public_item_prefix)
        VALUES
            (1, 'yoke', 'Yoke', 'main',
             '2026-01-01T00:00:00Z', 'upyoke/yoke', 'YOK');

        CREATE TABLE ouroboros_entries (
            id INTEGER PRIMARY KEY,
            agent TEXT,
            context TEXT,
            category TEXT,
            body TEXT,
            created_at TEXT,
            reviewed_at TEXT,
            archived_at TEXT
        );

        CREATE TABLE harness_sessions (
            session_id TEXT PRIMARY KEY,
            ended_at TEXT
        );
        INSERT INTO harness_sessions (session_id, ended_at)
        VALUES ('past', '2026-01-01T00:00:00Z');

        CREATE TABLE work_claims (
            id INTEGER PRIMARY KEY,
            session_id TEXT,
            target_kind TEXT,
            item_id INTEGER,
            epic_id INTEGER,
            task_num INTEGER,
            released_at TEXT
        );

        CREATE TABLE path_claims (
            id INTEGER PRIMARY KEY,
            state TEXT,
            owner_kind TEXT,
            owner_item_id INTEGER,
            item_id INTEGER
        );
    """))
    return conn


def _args(**kw) -> DoctorArgs:
    return DoctorArgs(**kw)


def _run_hc(fn, conn=None, **kw):
    """Run a single HC and return the RecordCollector."""
    owns_conn = conn is None
    if owns_conn:
        conn = _make_conn()
    rec = RecordCollector()
    try:
        fn(conn, _args(**kw), rec)
    finally:
        if owns_conn:
            conn.close()
    return rec


def _make_completed(returncode=0, stdout="", stderr=""):
    """Create a mock CompletedProcess."""
    import subprocess
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


class TestHcEpicTaskWorktreeBackfill:
    """Tests for hc_epic_task_worktree_backfill."""

    def test_empty_worktree_warns(self):
        conn = _make_conn()
        conn.execute(
            "INSERT INTO items (id, title, type, status) "
            "VALUES (100, 'Test Epic', 'epic', 'implementing')"
        )
        conn.execute(
            "INSERT INTO epic_tasks (epic_id, task_num, title, status) "
            "VALUES (100, 1, 'Task 1', 'pending')"
        )
        rec = _run_hc(hc_epic_task_worktree_backfill, conn)
        assert rec.results[0].result == "WARN"
        assert "task 1" in rec.results[0].detail

    def test_all_tasks_have_worktree_passes(self):
        conn = _make_conn()
        conn.execute(
            "INSERT INTO items (id, title, type, status) "
            "VALUES (100, 'Test Epic', 'epic', 'implementing')"
        )
        conn.execute(
            "INSERT INTO epic_tasks (epic_id, task_num, title, status, worktree) "
            "VALUES (100, 1, 'Task 1', 'pending', 'YOK-100')"
        )
        rec = _run_hc(hc_epic_task_worktree_backfill, conn)
        assert rec.results[0].result == "PASS"


class TestHcWorktreeHealth:
    """Tests for hc_worktree_health."""

    @patch("yoke_core.engines.doctor_report._resolve_repo_root", return_value="/fake/repo")
    @patch("yoke_core.engines.doctor_report._run")
    def test_clean_worktrees_pass(self, mock_run, mock_root):
        mock_run.side_effect = [
            _make_completed(stdout=(
                "worktree /fake/repo\n"
                "branch refs/heads/main\n"
                "\n"
            )),
        ]
        conn = _make_conn()
        rec = _run_hc(hc_worktree_health, conn)
        assert rec.results[0].result == "PASS"

    @patch("yoke_core.engines.doctor_report._resolve_repo_root", return_value=None)
    @patch("yoke_core.engines.doctor_report._run")
    def test_dirty_worktree_warns(self, mock_run, mock_root):
        """Test dirty worktree detection.

        We set _resolve_repo_root=None so the worktrees-dir scan is skipped,
        and only the git-worktree-list path runs.
        """
        mock_run.side_effect = [
            _make_completed(stdout=(
                "worktree /fake/repo\n"
                "branch refs/heads/main\n"
                "\n"
                "worktree /fake/wt/YOK-9999\n"
                "branch refs/heads/YOK-9999\n"
                "\n"
            )),
            _make_completed(stdout="M file.py\n"),
        ]
        conn = _make_conn()
        conn.execute(
            "INSERT INTO items (id, title, type, status) "
            "VALUES (42, 'Test', 'issue', 'implementing')"
        )
        with patch.object(Path, "is_dir", return_value=True):
            rec = _run_hc(hc_worktree_health, conn)
        assert rec.results[0].result == "WARN"
        assert "uncommitted changes" in rec.results[0].detail


class TestHcPathConfabulation:
    """Tests for hc_path_confabulation."""

    @patch("yoke_core.engines.doctor_report._resolve_repo_root", return_value="/fake/repo")
    def test_no_confabulation_passes(self, mock_root):
        conn = _make_conn()
        rec = _run_hc(hc_path_confabulation, conn)
        assert rec.results[0].result == "PASS"

    @patch("yoke_core.engines.doctor_report._resolve_repo_root", return_value="/fake/repo")
    def test_confabulated_ouroboros_entry_warns(self, mock_root):
        conn = _make_conn()
        conn.execute(
            "INSERT INTO ouroboros_entries (id, body) "
            "VALUES (1, 'Found issue in ouraboros/patterns.md')"
        )
        rec = _run_hc(hc_path_confabulation, conn)
        assert rec.results[0].result == "WARN"
        assert "ouroboros_entries" in rec.results[0].detail

    @patch("yoke_core.engines.doctor_report._resolve_repo_root", return_value="/fake/repo")
    def test_suppressed_line_passes(self, mock_root):
        conn = _make_conn()
        conn.execute(
            "INSERT INTO ouroboros_entries (id, body) "
            "VALUES (1, 'The word ouraboros here <!-- not-confabulated -->')"
        )
        rec = _run_hc(hc_path_confabulation, conn)
        assert rec.results[0].result == "PASS"


class TestHcOrphanedTempFiles:
    """Tests for hc_orphaned_temp_files.

    The scanner enumerates known kind directories across the global
    project/session/run tree. Each test isolates that tree via
    ``YOKE_SCRATCH_ROOT``.
    """

    @patch("yoke_core.engines.doctor_report._resolve_repo_root", return_value="/fake/repo")
    def test_no_temp_files_passes(self, mock_root, tmp_path, monkeypatch):
        monkeypatch.setenv("YOKE_SCRATCH_ROOT", str(tmp_path))
        rec = _run_hc(hc_orphaned_temp_files)
        assert rec.results[0].result == "PASS"

    @patch("yoke_core.engines.doctor_report._resolve_repo_root", return_value="/fake/repo")
    def test_stale_ephemeral_residue_warns(self, mock_root, tmp_path, monkeypatch):
        # Preserves the legacy 300s (ephemeral residue) threshold: a
        # stale watcher-captures file older than 300s warns.
        monkeypatch.setenv("YOKE_SCRATCH_ROOT", str(tmp_path))
        captures_dir = (
            tmp_path / "other" / "sessions" / "past" / "runs" / "old"
            / "watcher-captures"
        )
        captures_dir.mkdir(parents=True)
        stale_file = captures_dir / "yoke-pytest.raw.abc.log"
        stale_file.write_text("")
        old_epoch = int(time.time()) - 3600
        os.utime(stale_file, (old_epoch, old_epoch))

        rec = _run_hc(hc_orphaned_temp_files)
        assert rec.results[0].result == "WARN"
        assert "yoke-pytest.raw.abc.log" in rec.results[0].detail
        assert "kind=watcher-captures" in rec.results[0].detail

    @patch("yoke_core.engines.doctor_report._resolve_repo_root", return_value="/fake/repo")
    def test_unknown_durable_storage_is_preserved(
        self, mock_root, tmp_path, monkeypatch
    ):
        # Durable storage is not one generic disposable bucket. Unknown helper
        # state stays intact until its owner has an explicit cleanup contract.
        monkeypatch.setenv("YOKE_SCRATCH_ROOT", str(tmp_path))
        storage_dir = (
            tmp_path / "other" / "sessions" / "past" / "runs" / "old"
            / "storage" / "db_error_hook"
        )
        storage_dir.mkdir(parents=True)
        stale_file = storage_dir / "collapse-state-stale.json"
        stale_file.write_text("{}")
        old_epoch = int(time.time()) - 3600
        os.utime(stale_file, (old_epoch, old_epoch))
        os.utime(storage_dir, (old_epoch, old_epoch))

        rec = _run_hc(hc_orphaned_temp_files)
        assert rec.results[0].result == "PASS"
        assert stale_file.read_text(encoding="utf-8") == "{}"

    @patch("yoke_core.engines.doctor_report._resolve_repo_root", return_value="/fake/repo")
    def test_fresh_residue_passes(self, mock_root, tmp_path, monkeypatch):
        # An ephemeral residue file under the 300s threshold should not
        # warn — the scanner respects the per-sub-directory threshold.
        monkeypatch.setenv("YOKE_SCRATCH_ROOT", str(tmp_path))
        captures_dir = (
            tmp_path / "other" / "sessions" / "past" / "runs" / "old"
            / "watcher-captures"
        )
        captures_dir.mkdir(parents=True)
        fresh_file = captures_dir / "yoke-pytest.raw.fresh.log"
        fresh_file.write_text("")
        # mtime ~now() means age < 300s — under the ephemeral threshold.
        rec = _run_hc(hc_orphaned_temp_files)
        assert rec.results[0].result == "PASS"
