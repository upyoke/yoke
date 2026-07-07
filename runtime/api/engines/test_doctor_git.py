"""Tests for the doctor engine: core git-state HCs.

Worktree, filesystem, and stale-remote-branch HCs live in
test_doctor_git_worktrees.py. GitHub-dependent HCs and registration tests
live in test_doctor_git_github.py.

Tests use mock subprocess to avoid real git calls.
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import patch

from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
from yoke_core.engines._project_identity_test_helpers import (
    _insert_item,
    _seed_project,
)
from yoke_core.engines.doctor import (
    DoctorArgs,
    RecordCollector,
    hc_branch_divergence,
    hc_cross_project_commits,
    hc_main_checkout,
    hc_orphaned_stashes,
    hc_uncaptured_discoveries,
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
    """))
    return conn


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


def _args(**kw) -> DoctorArgs:
    return DoctorArgs(**kw)


def _make_completed(returncode=0, stdout="", stderr=""):
    """Create a mock CompletedProcess."""
    import subprocess
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


class TestHcMainCheckout:
    """Tests for hc_main_checkout."""

    @patch("yoke_core.engines.doctor_report._resolve_main_root", return_value=None)
    def test_no_main_root_warns(self, mock_root):
        rec = _run_hc(hc_main_checkout)
        assert rec.results[0].result == "WARN"
        assert "Could not resolve" in rec.results[0].detail

    @patch("yoke_core.engines.doctor_report._resolve_main_root", return_value="/fake/repo")
    @patch("yoke_core.engines.doctor_report._run")
    def test_main_branch_passes(self, mock_run, mock_root):
        # Make .git dir exist
        with patch.object(Path, "exists", return_value=True):
            mock_run.return_value = _make_completed(stdout="main\n")
            rec = _run_hc(hc_main_checkout)
            assert rec.results[0].result == "PASS"

    @patch("yoke_core.engines.doctor_report._resolve_main_root", return_value="/fake/repo")
    @patch("yoke_core.engines.doctor_report._run")
    def test_detached_head_warns(self, mock_run, mock_root):
        with patch.object(Path, "exists", return_value=True):
            mock_run.return_value = _make_completed(stdout="HEAD\n")
            rec = _run_hc(hc_main_checkout)
            assert rec.results[0].result == "WARN"
            assert "detached HEAD" in rec.results[0].detail

    @patch("yoke_core.engines.doctor_report._resolve_main_root", return_value="/fake/repo")
    @patch("yoke_core.engines.doctor_report._run")
    def test_wrong_branch_warns(self, mock_run, mock_root):
        with patch.object(Path, "exists", return_value=True):
            mock_run.return_value = _make_completed(stdout="feature-branch\n")
            rec = _run_hc(hc_main_checkout)
            assert rec.results[0].result == "WARN"
            assert "feature-branch" in rec.results[0].detail


class TestHcBranchDivergence:
    """Tests for hc_branch_divergence."""

    @patch("yoke_core.engines.doctor_report._run")
    def test_no_divergence_passes(self, mock_run):
        same_hash = "abc123\n"
        mock_run.side_effect = [
            # git rev-parse --verify main
            _make_completed(stdout="abc\n"),
            # git fetch
            _make_completed(),
            # git rev-parse main
            _make_completed(stdout=same_hash),
            # git rev-parse origin/main
            _make_completed(stdout=same_hash),
        ]
        rec = _run_hc(hc_branch_divergence)
        assert rec.results[0].result == "PASS"

    @patch("yoke_core.engines.doctor_report._run")
    def test_divergence_warns(self, mock_run):
        mock_run.side_effect = [
            # git rev-parse --verify main
            _make_completed(stdout="abc\n"),
            # git fetch
            _make_completed(),
            # git rev-parse main
            _make_completed(stdout="abc123\n"),
            # git rev-parse origin/main
            _make_completed(stdout="def456\n"),
            # git rev-list ahead
            _make_completed(stdout="3\n"),
            # git rev-list behind
            _make_completed(stdout="2\n"),
        ]
        rec = _run_hc(hc_branch_divergence)
        assert rec.results[0].result == "WARN"
        assert "3 ahead" in rec.results[0].detail
        assert "2 behind" in rec.results[0].detail


class TestHcUncapturedDiscoveries:
    """Tests for hc_uncaptured_discoveries."""

    @patch("yoke_core.engines.doctor_report._run")
    def test_clean_history_passes(self, mock_run):
        mock_run.return_value = _make_completed(
            stdout="abc1234 YOK-123: add feature\ndef5678 YOK-456: update docs\n"
        )
        rec = _run_hc(hc_uncaptured_discoveries)
        assert rec.results[0].result == "PASS"

    @patch("yoke_core.engines.doctor_report._run")
    def test_discovery_without_sun_ref_warns(self, mock_run):
        mock_run.return_value = _make_completed(
            stdout="abc1234 fix broken thing\ndef5678 YOK-456: update docs\n"
        )
        rec = _run_hc(hc_uncaptured_discoveries)
        assert rec.results[0].result == "WARN"
        assert "fix broken thing" in rec.results[0].detail

    @patch("yoke_core.engines.doctor_report._run")
    def test_discovery_with_sun_ref_passes(self, mock_run):
        mock_run.return_value = _make_completed(
            stdout="abc1234 YOK-99: fix broken thing\n"
        )
        rec = _run_hc(hc_uncaptured_discoveries)
        assert rec.results[0].result == "PASS"


class TestHcOrphanedStashes:
    """Tests for hc_orphaned_stashes."""

    @patch("yoke_core.engines.doctor_report._run")
    def test_no_stashes_passes(self, mock_run):
        mock_run.return_value = _make_completed(stdout="")
        rec = _run_hc(hc_orphaned_stashes)
        assert rec.results[0].result == "PASS"

    @patch("yoke_core.engines.doctor_report._run")
    def test_orphaned_stash_warns(self, mock_run):
        mock_run.return_value = _make_completed(
            stdout="stash@{0}: On main: yoke-pre-rebase-YOK-9999\n"
        )
        rec = _run_hc(hc_orphaned_stashes)
        assert rec.results[0].result == "WARN"
        assert "yoke-pre-rebase-" in rec.results[0].detail

    @patch("yoke_core.engines.doctor_report._run")
    def test_normal_stash_passes(self, mock_run):
        mock_run.return_value = _make_completed(
            stdout="stash@{0}: On main: WIP on feature\n"
        )
        rec = _run_hc(hc_orphaned_stashes)
        assert rec.results[0].result == "PASS"


class TestHcCrossProjectCommits:
    """Tests for hc_cross_project_commits."""

    @patch("yoke_core.engines.doctor_report._run")
    def test_no_cross_project_passes(self, mock_run):
        conn = _make_conn()
        # No non-yoke done items
        rec = _run_hc(hc_cross_project_commits, conn)
        assert rec.results[0].result == "PASS"

    @patch("yoke_core.engines.doctor_report._run")
    def test_contaminated_commit_warns(self, mock_run):
        conn = _make_conn()
        _seed_project(conn, "buzz")
        _insert_item(conn, 42, "Buzz fix", project="buzz",
                     type="issue", status="done")
        mock_run.side_effect = [
            # git log for the item
            _make_completed(stdout="aabbccddee\n"),
            # git diff-tree for that commit
            _make_completed(stdout="src/main.py\nyoke/backlog/042.md\n"),
        ]
        rec = _run_hc(hc_cross_project_commits, conn)
        assert rec.results[0].result == "WARN"
        assert "YOK-42" in rec.results[0].detail
        assert "src/main.py" in rec.results[0].detail

    @patch("yoke_core.engines.doctor_report._run")
    def test_bookkeeping_only_passes(self, mock_run):
        conn = _make_conn()
        _seed_project(conn, "buzz")
        _insert_item(conn, 42, "Buzz fix", project="buzz",
                     type="issue", status="done")
        mock_run.side_effect = [
            # git log for the item
            _make_completed(stdout="aabbccddee\n"),
            # git diff-tree: only bookkeeping files
            _make_completed(stdout="ouroboros/simulation-YOK-42.md\n"),
        ]
        rec = _run_hc(hc_cross_project_commits, conn)
        assert rec.results[0].result == "PASS"
