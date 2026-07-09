"""Tests for GitHub-dependent doctor HCs and HC registration.

Git-state HCs live in test_doctor_git.py.
Worktree/filesystem/stale-branch HCs live in test_doctor_git_worktrees.py.

Tests use mock subprocess to avoid real gh calls.
"""

from __future__ import annotations

import json
import textwrap
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
    hc_delegated_sync,
    hc_gh_orphan_detection,
    hc_orphaned_gh_issues,
    hc_wrong_repo_issues,
    _should_run_hc,
    HEALTH_CHECKS,
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


def _auth(repo: str = "upyoke/yoke"):
    """Build a ProjectGithubAuth stub for resolver patches."""
    from yoke_core.domain.project_github_auth import ProjectGithubAuth
    return ProjectGithubAuth(project="yoke", repo=repo, token="t", env={"GH_TOKEN": "t"})


class TestHcOrphanedGhIssues:
    """Tests for hc_orphaned_gh_issues."""

    @patch("yoke_core.engines.doctor_hc_worktrees._github_auth_configured", return_value=False)
    def test_no_github_auth_skips(self, mock_gh):
        rec = _run_hc(hc_orphaned_gh_issues)
        assert rec.results[0].result == "SKIP"
        assert "GitHub App repo binding is not available" in rec.results[0].detail

    @patch("yoke_core.engines.doctor_hc_worktrees._github_auth_configured", return_value=True)
    @patch("yoke_core.engines.doctor_hc_worktrees_gh.resolve_project_github_auth",
           side_effect=lambda project, db_path=None: _auth())
    @patch("yoke_core.engines.doctor_hc_worktrees_gh.list_issues_by_labels_rest")
    def test_no_orphans_passes(self, mock_rest, mock_resolve, mock_avail):
        conn = _make_conn()
        _seed_project(conn, "yoke", github_repo="upyoke/yoke")
        conn.execute(
            "INSERT INTO items (id, title, type, status, github_issue) "
            "VALUES (1, 'Test', 'issue', 'idea', '#100')"
        )
        mock_rest.return_value = _make_completed(stdout="100\n")
        rec = _run_hc(hc_orphaned_gh_issues, conn)
        assert rec.results[0].result == "PASS"


class TestHcGhOrphanDetection:
    """Tests for hc_gh_orphan_detection."""

    @patch("yoke_core.engines.doctor_hc_worktrees._github_auth_configured", return_value=False)
    def test_no_github_auth_skips(self, mock_gh):
        rec = _run_hc(hc_gh_orphan_detection)
        assert rec.results[0].result == "SKIP"
        assert "GitHub App repo binding is not available" in rec.results[0].detail

    @patch("yoke_core.engines.doctor_hc_worktrees._github_auth_configured", return_value=True)
    @patch("yoke_core.engines.doctor_hc_worktrees_gh.resolve_project_github_auth",
           side_effect=lambda project, db_path=None: _auth())
    @patch("yoke_core.engines.doctor_hc_worktrees_gh.search_issues_by_query_rest")
    def test_orphan_detected_warns(self, mock_rest, mock_resolve, mock_avail):
        conn = _make_conn()
        _seed_project(conn, "yoke", github_repo="upyoke/yoke")
        gh_json = json.dumps([{"number": 999, "title": "[YOK-999] orphan", "state": "OPEN"}])
        mock_rest.return_value = _make_completed(stdout=gh_json)
        rec = _run_hc(hc_gh_orphan_detection, conn)
        assert rec.results[0].result == "WARN"
        assert "#999" in rec.results[0].detail


class TestHcWrongRepoIssues:
    """Tests for hc_wrong_repo_issues."""

    @patch("yoke_core.engines.doctor_hc_worktrees._github_auth_configured", return_value=False)
    def test_no_github_auth_skips(self, mock_gh):
        rec = _run_hc(hc_wrong_repo_issues)
        assert rec.results[0].result == "SKIP"
        assert "GitHub App repo binding is not available" in rec.results[0].detail

    @patch("yoke_core.engines.doctor_hc_worktrees._github_auth_configured", return_value=True)
    @patch("yoke_core.engines.doctor_hc_worktrees_gh_repo.resolve_project_github_auth",
           side_effect=lambda project, db_path=None: _auth())
    @patch("yoke_core.engines.doctor_hc_worktrees_gh_repo.issue_view_state")
    def test_issue_in_correct_repo_passes(self, mock_gh_run, mock_resolve, mock_avail):
        conn = _make_conn()
        _seed_project(conn, "buzz", github_repo="example-org/buzz")
        _insert_item(conn, 42, "Buzz item", project="buzz",
                     type="issue", status="idea", github_issue="#100")
        mock_gh_run.return_value = _make_completed(stdout="OPEN\n")
        rec = _run_hc(hc_wrong_repo_issues, conn)
        assert rec.results[0].result == "PASS"

    @patch("yoke_core.engines.doctor_hc_worktrees._github_auth_configured", return_value=True)
    @patch("yoke_core.engines.doctor_hc_worktrees_gh_repo.resolve_project_github_auth",
           side_effect=lambda project, db_path=None: _auth())
    @patch("yoke_core.engines.doctor_hc_worktrees_gh_repo.issue_view_state")
    def test_issue_in_wrong_repo_warns(self, mock_gh_run, mock_resolve, mock_avail):
        conn = _make_conn()
        _seed_project(conn, "buzz", github_repo="example-org/buzz")
        _insert_item(conn, 42, "Buzz item", project="buzz",
                     type="issue", status="idea", github_issue="#100")
        mock_gh_run.side_effect = [
            _make_completed(returncode=1, stdout=""),  # not in buzz repo
            _make_completed(stdout="OPEN\n"),           # found in yoke repo
        ]
        rec = _run_hc(hc_wrong_repo_issues, conn)
        assert rec.results[0].result == "WARN"
        assert "wrong repo" in rec.results[0].detail.lower()


class TestHcDelegatedSync:
    """Tests for hc_delegated_sync (resync engine delegation)."""

    @patch("yoke_core.engines.doctor_report._run")
    def test_parses_doctor_format(self, mock_run):
        mock_run.return_value = _make_completed(
            stdout=(
                "HC-title-drift|Title drift|PASS|\n"
                "HC-body-drift|Body drift|WARN|YOK-1: body mismatch\n"
                "HC-missing-gh-issues|Missing GitHub issues|PASS|\n"
                "HC-orphan-epic-tasks|Orphan epic tasks|PASS|\n"
                "HC-reverse-completeness|Reverse completeness|PASS|\n"
                "HC-comment-sync|Comment sync|PASS|\n"
                "HC-label-drift|Label drift|PASS|\n"
                "HC-state-drift|State drift|PASS|\n"
                "HC-frozen-label-drift|Frozen label drift|PASS|\n"
                "HC-task-label-drift|Task label drift|PASS|\n"
            ),
        )
        conn = _make_conn()
        rec = RecordCollector()
        fn_args = DoctorArgs()
        hc_delegated_sync(conn, fn_args, rec)
        slugs = [r.check_id for r in rec.results]
        assert "HC-title-drift" in slugs
        assert "HC-body-drift" in slugs
        body_drift = [r for r in rec.results if r.check_id == "HC-body-drift"][0]
        assert body_drift.result == "WARN"

    @patch("yoke_core.engines.doctor_report._run")
    def test_fallback_on_no_output(self, mock_run):
        mock_run.return_value = _make_completed(returncode=2, stdout="")
        conn = _make_conn()
        rec = RecordCollector()
        fn_args = DoctorArgs()
        hc_delegated_sync(conn, fn_args, rec)
        assert all(r.result == "WARN" for r in rec.results)
        assert len(rec.results) == 11  # 10 + blocked-label-drift


class TestQuickMode:
    """Verify --quick mode skips GitHub-dependent HCs."""

    def test_quick_skips_github_hcs(self):
        args = DoctorArgs(quick=True)
        assert not _should_run_hc("orphaned-gh-issues", args)
        assert not _should_run_hc("stale-remote-branches", args)
        assert not _should_run_hc("wrong-repo-issues", args)
        assert not _should_run_hc("delegated-sync", args)

    def test_quick_allows_git_hcs(self):
        args = DoctorArgs(quick=True)
        assert _should_run_hc("main-checkout", args)
        assert _should_run_hc("worktree-health", args)
        assert _should_run_hc("branch-divergence", args)
        assert _should_run_hc("uncaptured-discoveries", args)
        assert _should_run_hc("orphaned-stashes", args)


class TestOnlyDelegatedSync:
    """Verify --only correctly triggers delegated-sync for sub-HCs."""

    def test_only_title_drift_triggers_delegated(self):
        args = DoctorArgs(only="title-drift")
        assert _should_run_hc("delegated-sync", args)

    def test_only_unrelated_does_not_trigger_delegated(self):
        args = DoctorArgs(only="main-checkout")
        assert not _should_run_hc("delegated-sync", args)


class TestHcRegistration:
    """Verify all new HCs are registered in HEALTH_CHECKS."""

    def test_git_hcs_registered(self):
        slugs = {hc.slug for hc in HEALTH_CHECKS}
        for expected in [
            "main-checkout", "worktree-health", "branch-divergence",
            "uncaptured-discoveries", "orphaned-stashes", "cross-project-commits",
            "epic-task-worktree-backfill", "path-confabulation",
            "orphaned-temp-files",
        ]:
            assert expected in slugs, f"{expected} not in HEALTH_CHECKS"

    def test_github_hcs_registered(self):
        slugs = {hc.slug for hc in HEALTH_CHECKS}
        for expected in [
            "stale-remote-branches", "orphaned-gh-issues",
            "gh-orphan-detection", "wrong-repo-issues",
            "delegated-sync",
        ]:
            assert expected in slugs, f"{expected} not in HEALTH_CHECKS"

    def test_github_hcs_marked_dependent(self):
        gh_hcs = [hc for hc in HEALTH_CHECKS if hc.slug in (
            "stale-remote-branches", "orphaned-gh-issues",
            "gh-orphan-detection", "wrong-repo-issues", "delegated-sync",
        )]
        for hc in gh_hcs:
            assert hc.github_dependent, f"{hc.slug} should be github_dependent=True"
