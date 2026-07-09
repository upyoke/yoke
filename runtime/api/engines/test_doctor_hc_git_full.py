"""Doctor HC tests for delegated-sync and gh-orphan-detection.

Wrong-repo/orphaned-active-items tests live in test_doctor_hc_git_full_repos.py.
Worktree-health/stale-remote-branches tests live in test_doctor_hc_git_full_worktree.py.
Orphaned-gh-issues tests live in test_doctor_hc_git_full_orphans.py.

Schema scaffolding is shared via _doctor_hc_git_test_helpers (private module).
Uses mock subprocess calls for deterministic testing — no real git/gh needed.
"""

from __future__ import annotations

import json
from unittest.mock import patch

from yoke_core.engines._doctor_hc_git_test_helpers import (
    _completed,
    _make_conn,
    _result,
    _run_hc,
)
from yoke_core.engines._project_identity_test_helpers import _seed_project
from yoke_core.engines.doctor import (
    RecordCollector,
    _DELEGATED_SYNC_HCS,
    hc_delegated_sync,
    hc_gh_orphan_detection,
)


class TestDelegatedSync:
    """Tests for hc_delegated_sync: resync engine delegation."""

    @patch("yoke_core.engines.doctor_report._run")
    def test_all_pass_parsed(self, mock_run):
        """TEST 1: All PASS -- mock resync exits 0, all HCs pass."""
        mock_run.return_value = _completed(stdout=(
            "HC-missing-gh-issues|Missing GitHub issues|PASS|0 missing\n"
            "HC-title-drift|Title drift|PASS|0 drifts\n"
            "HC-body-drift|Body drift|PASS|0 drifts\n"
            "HC-reverse-completeness|Reverse completeness|PASS|0 orphans\n"
            "HC-comment-sync|Comment sync|PASS|0 drifts\n"
            "HC-label-drift|Label drift|PASS|0 drifts\n"
            "HC-state-drift|State drift|PASS|0 drifts\n"
            "HC-frozen-label-drift|Frozen label drift|PASS|0 drifts\n"
            "HC-blocked-label-drift|Blocked label drift|PASS|0 drifts\n"
            "HC-task-label-drift|Task label drift|PASS|0 drifts\n"
            "HC-orphan-epic-tasks|Orphan epic tasks|PASS|0 orphans\n"
        ))
        rec = _run_hc(hc_delegated_sync)
        slugs = {r.check_id for r in rec.results}
        assert "HC-missing-gh-issues" in slugs
        assert "HC-title-drift" in slugs
        assert "HC-label-drift" in slugs
        assert "HC-state-drift" in slugs
        for r in rec.results:
            assert r.result == "PASS"

    @patch("yoke_core.engines.doctor_report._run")
    def test_exit1_output_preserved(self, mock_run):
        """TEST 2: Drift found -- exit 1. Output must be preserved (regression)."""
        mock_run.return_value = _completed(returncode=1, stdout=(
            "HC-missing-gh-issues|Missing GitHub issues|FAIL|2 items: YOK-10, YOK-15\n"
            "HC-title-drift|Title drift|PASS|0 drifts\n"
            "HC-body-drift|Body drift|WARN|1 drift: YOK-10\n"
            "HC-reverse-completeness|Reverse completeness|PASS|0 orphans\n"
            "HC-comment-sync|Comment sync|PASS|0 drifts\n"
            "HC-label-drift|Label drift|WARN|1 drift: YOK-10\n"
            "HC-state-drift|State drift|PASS|0 drifts\n"
            "HC-frozen-label-drift|Frozen label drift|PASS|0 drifts\n"
            "HC-blocked-label-drift|Blocked label drift|PASS|0 drifts\n"
            "HC-task-label-drift|Task label drift|PASS|0 drifts\n"
            "HC-orphan-epic-tasks|Orphan epic tasks|PASS|0 orphans\n"
        ))
        rec = _run_hc(hc_delegated_sync)
        by_id = {r.check_id: r for r in rec.results}
        assert by_id["HC-missing-gh-issues"].result == "FAIL"
        assert "YOK-10" in by_id["HC-missing-gh-issues"].detail
        assert by_id["HC-body-drift"].result == "WARN"
        assert by_id["HC-label-drift"].result == "WARN"
        assert by_id["HC-title-drift"].result == "PASS"
        assert by_id["HC-state-drift"].result == "PASS"

    @patch("yoke_core.engines.doctor_report._run")
    def test_no_output_fallback(self, mock_run):
        """TEST 3: No output -- WARN fallback for all delegated HCs."""
        mock_run.return_value = _completed(returncode=2, stdout="")
        rec = _run_hc(hc_delegated_sync)
        assert all(r.result == "WARN" for r in rec.results)
        assert len(rec.results) == 11  # 10 + blocked-label-drift

    @patch("yoke_core.engines.doctor_report._run")
    def test_only_parent_slug_runs_all_delegated_hcs(self, mock_run):
        mock_run.return_value = _completed(returncode=2, stdout="")
        rec = _run_hc(hc_delegated_sync, only="delegated-sync")
        assert len(rec.results) == 11
        assert {r.check_id for r in rec.results} == {
            f"HC-{slug}" for slug in _DELEGATED_SYNC_HCS
        }

    @patch(
        "yoke_core.engines.doctor_hc_worktrees_gh.runtime_settings.get_seconds",
        return_value=7,
    )
    @patch("yoke_core.engines.doctor_report._run")
    def test_timeout_records_explicit_warnings(self, mock_run, mock_timeout):
        """TEST 4: timeout is bounded and reported per delegated HC."""
        mock_run.return_value = _completed(
            returncode=124, stdout="", stderr="timeout after 7s",
        )
        rec = _run_hc(hc_delegated_sync)
        assert mock_run.call_args.kwargs["timeout"] == 7
        assert len(rec.results) == 11
        assert all(r.result == "WARN" for r in rec.results)
        assert all("resync engine timed out after 7s" in r.detail for r in rec.results)
        assert all("python3 -m yoke_core.engines.resync" in r.detail for r in rec.results)

    @patch("yoke_core.engines.doctor_report._run")
    def test_mixed_results(self, mock_run):
        """TEST 5: Mixed PASS/FAIL/WARN independently parsed."""
        mock_run.return_value = _completed(returncode=1, stdout=(
            "HC-missing-gh-issues|Missing GitHub issues|PASS|0 missing\n"
            "HC-title-drift|Title drift|FAIL|3 drifts: YOK-5, YOK-8, YOK-12\n"
            "HC-body-drift|Body drift|WARN|1 drift: YOK-5\n"
            "HC-reverse-completeness|Reverse completeness|FAIL|2 orphans: #100, #200\n"
            "HC-comment-sync|Comment sync|PASS|0 drifts\n"
            "HC-label-drift|Label drift|FAIL|2 drifts\n"
            "HC-state-drift|State drift|PASS|0 drifts\n"
            "HC-frozen-label-drift|Frozen label drift|PASS|0 drifts\n"
            "HC-blocked-label-drift|Blocked label drift|PASS|0 drifts\n"
            "HC-task-label-drift|Task label drift|PASS|0 drifts\n"
            "HC-orphan-epic-tasks|Orphan epic tasks|PASS|0 orphans\n"
        ))
        rec = _run_hc(hc_delegated_sync)
        by_id = {r.check_id: r for r in rec.results}
        assert by_id["HC-missing-gh-issues"].result == "PASS"
        assert by_id["HC-title-drift"].result == "FAIL"
        assert by_id["HC-body-drift"].result == "WARN"
        assert by_id["HC-reverse-completeness"].result == "FAIL"
        assert by_id["HC-comment-sync"].result == "PASS"
        assert by_id["HC-label-drift"].result == "FAIL"
        assert by_id["HC-state-drift"].result == "PASS"

    @patch("yoke_core.engines.doctor_report._run")
    def test_fix_mode_propagation(self, mock_run):
        """TEST 6: --fix passed through to resync subprocess."""
        mock_run.return_value = _completed(stdout=(
            "HC-missing-gh-issues|Missing GitHub issues|PASS|0\n"
            "HC-title-drift|Title drift|PASS|0\n"
            "HC-body-drift|Body drift|PASS|0\n"
            "HC-reverse-completeness|Reverse completeness|PASS|0\n"
            "HC-comment-sync|Comment sync|PASS|0\n"
            "HC-label-drift|Label drift|PASS|0\n"
            "HC-state-drift|State drift|PASS|0\n"
            "HC-frozen-label-drift|Frozen label drift|PASS|0\n"
            "HC-task-label-drift|Task label drift|PASS|0\n"
            "HC-orphan-epic-tasks|Orphan epic tasks|PASS|0\n"
        ))
        rec = _run_hc(hc_delegated_sync, fix=True)
        # Verify the call included --fix flag
        cmd = mock_run.call_args[0][0]
        cmd_str = " ".join(cmd) if isinstance(cmd, list) else cmd
        assert "--fix" in cmd_str

    @patch("yoke_core.engines.doctor_report._run")
    def test_detect_only_propagation(self, mock_run):
        """TEST 7: --detect-only passed when not in fix mode."""
        mock_run.return_value = _completed(stdout=(
            "HC-missing-gh-issues|Missing GitHub issues|PASS|0\n"
            "HC-title-drift|Title drift|PASS|0\n"
            "HC-body-drift|Body drift|PASS|0\n"
            "HC-reverse-completeness|Reverse completeness|PASS|0\n"
            "HC-comment-sync|Comment sync|PASS|0\n"
            "HC-label-drift|Label drift|PASS|0\n"
            "HC-state-drift|State drift|PASS|0\n"
            "HC-frozen-label-drift|Frozen label drift|PASS|0\n"
            "HC-task-label-drift|Task label drift|PASS|0\n"
            "HC-orphan-epic-tasks|Orphan epic tasks|PASS|0\n"
        ))
        rec = _run_hc(hc_delegated_sync, fix=False)
        cmd = mock_run.call_args[0][0]
        cmd_str = " ".join(cmd) if isinstance(cmd, list) else cmd
        assert "--detect-only" in cmd_str

    @patch("yoke_core.engines.doctor_report._run")
    def test_db_path_propagation(self, mock_run):
        """Doctor's test/override db-path token is passed to resync."""
        mock_run.return_value = _completed(stdout=(
            "HC-missing-gh-issues|Missing GitHub issues|PASS|0\n"
            "HC-title-drift|Title drift|PASS|0\n"
            "HC-body-drift|Body drift|PASS|0\n"
            "HC-reverse-completeness|Reverse completeness|PASS|0\n"
            "HC-comment-sync|Comment sync|PASS|0\n"
            "HC-label-drift|Label drift|PASS|0\n"
            "HC-state-drift|State drift|PASS|0\n"
            "HC-frozen-label-drift|Frozen label drift|PASS|0\n"
            "HC-task-label-drift|Task label drift|PASS|0\n"
            "HC-orphan-epic-tasks|Orphan epic tasks|PASS|0\n"
        ))
        _run_hc(hc_delegated_sync, db_path="/tmp/doctor.db")
        cmd = mock_run.call_args[0][0]
        assert "--db-path" in cmd
        assert cmd[cmd.index("--db-path") + 1] == "/tmp/doctor.db"

    def test_label_state_drift_present(self):
        """TEST 8: HC-label-drift and HC-state-drift in delegated HC list."""
        assert "label-drift" in _DELEGATED_SYNC_HCS
        assert "state-drift" in _DELEGATED_SYNC_HCS


class TestGhOrphanDetection:
    """Tests for hc_gh_orphan_detection."""

    @patch("yoke_core.engines.doctor_hc_worktrees._github_auth_configured", return_value=False)
    def test_no_github_auth_skips(self, mock_gh):
        """T4: HC SKIPs with canonical reason when project GitHub App auth is unavailable."""
        rec = _run_hc(hc_gh_orphan_detection)
        assert _result(rec).result == "SKIP"
        assert "GitHub App repo binding is not available" in _result(rec).detail

    @patch("yoke_core.engines.doctor_hc_worktrees._github_auth_configured", return_value=True)
    @patch("yoke_core.engines.doctor_hc_worktrees_gh.resolve_project_github_auth",
           side_effect=lambda project, db_path=None: _auth("upyoke/yoke"))
    @patch("yoke_core.engines.doctor_hc_worktrees_gh.search_issues_by_query_rest")
    def test_orphan_detected(self, mock_gh_run, mock_resolve, mock_avail):
        """T1: Orphan issue (#999) detected."""
        conn = _make_conn()
        _seed_project(conn, "yoke", github_repo="upyoke/yoke")
        conn.execute(
            "INSERT INTO items (id, title, type, status, github_issue) "
            "VALUES (1, 'Tracked', 'issue', 'implementing', '#10')"
        )
        gh_json = json.dumps([
            {"number": 10, "title": "[YOK-1] Tracked", "state": "OPEN"},
            {"number": 999, "title": "[YOK-999] Orphaned", "state": "OPEN"},
        ])
        mock_gh_run.return_value = _completed(stdout=gh_json)
        rec = _run_hc(hc_gh_orphan_detection, conn)
        assert _result(rec).result == "WARN"
        assert "#999" in _result(rec).detail

    @patch("yoke_core.engines.doctor_hc_worktrees._github_auth_configured", return_value=True)
    @patch("yoke_core.engines.doctor_hc_worktrees_gh.resolve_project_github_auth",
           side_effect=lambda project, db_path=None: _auth("upyoke/yoke"))
    @patch("yoke_core.engines.doctor_hc_worktrees_gh.search_issues_by_query_rest")
    def test_known_issue_not_flagged(self, mock_gh_run, mock_resolve, mock_avail):
        """T2: Known issue is NOT flagged."""
        conn = _make_conn()
        _seed_project(conn, "yoke", github_repo="upyoke/yoke")
        conn.execute(
            "INSERT INTO items (id, title, type, status, github_issue) "
            "VALUES (1, 'Tracked', 'issue', 'implementing', '#10')"
        )
        gh_json = json.dumps([
            {"number": 10, "title": "[YOK-1] Tracked", "state": "OPEN"},
        ])
        mock_gh_run.return_value = _completed(stdout=gh_json)
        rec = _run_hc(hc_gh_orphan_detection, conn)
        assert _result(rec).result == "PASS"

    @patch("yoke_core.engines.doctor_hc_worktrees._github_auth_configured", return_value=True)
    @patch("yoke_core.engines.doctor_hc_worktrees_gh.resolve_project_github_auth",
           side_effect=lambda project, db_path=None: _auth("upyoke/yoke"))
    @patch("yoke_core.engines.doctor_hc_worktrees_gh.search_issues_by_query_rest")
    def test_epic_task_issue_not_flagged(self, mock_gh_run, mock_resolve, mock_avail):
        """T3: Epic task issue (#20) excluded from orphan detection."""
        conn = _make_conn()
        _seed_project(conn, "yoke", github_repo="upyoke/yoke")
        conn.execute(
            "INSERT INTO items (id, title, type, status, github_issue) "
            "VALUES (1, 'Tracked', 'issue', 'implementing', '#10')"
        )
        conn.execute(
            "INSERT INTO epic_tasks (epic_id, task_num, title, status, github_issue) "
            "VALUES ('my-epic', 1, 'Task', 'done', '#20')"
        )
        gh_json = json.dumps([
            {"number": 10, "title": "[YOK-1] Tracked", "state": "OPEN"},
            {"number": 20, "title": "[YOK-1] Task", "state": "CLOSED"},
        ])
        mock_gh_run.return_value = _completed(stdout=gh_json)
        rec = _run_hc(hc_gh_orphan_detection, conn)
        assert "#20" not in _result(rec).detail if _result(rec).detail else True

    @patch("yoke_core.engines.doctor_hc_worktrees._github_auth_configured", return_value=True)
    @patch("yoke_core.engines.doctor_hc_worktrees_gh.resolve_project_github_auth",
           side_effect=lambda project, db_path=None: _auth("upyoke/yoke"))
    @patch("yoke_core.engines.doctor_hc_worktrees_gh.search_issues_by_query_rest")
    def test_pass_no_github_issues(self, mock_gh_run, mock_resolve, mock_avail):
        """T5: PASS when no GitHub issues exist."""
        conn = _make_conn()
        _seed_project(conn, "yoke", github_repo="upyoke/yoke")
        mock_gh_run.return_value = _completed(stdout="[]")
        rec = _run_hc(hc_gh_orphan_detection, conn)
        assert _result(rec).result == "PASS"

    @patch("yoke_core.engines.doctor_hc_worktrees._github_auth_configured", return_value=True)
    @patch("yoke_core.engines.doctor_hc_worktrees_gh.resolve_project_github_auth",
           side_effect=lambda project, db_path=None: _auth("upyoke/yoke"))
    @patch("yoke_core.engines.doctor_hc_worktrees_gh.search_issues_by_query_rest")
    def test_multiple_orphans(self, mock_gh_run, mock_resolve, mock_avail):
        """T6: Multiple orphans detected."""
        conn = _make_conn()
        _seed_project(conn, "yoke", github_repo="upyoke/yoke")
        conn.execute(
            "INSERT INTO items (id, title, type, status, github_issue) "
            "VALUES (1, 'Tracked', 'issue', 'implementing', '#10')"
        )
        gh_json = json.dumps([
            {"number": 10, "title": "[YOK-1] Tracked", "state": "OPEN"},
            {"number": 50, "title": "[YOK-50] First orphan", "state": "OPEN"},
            {"number": 51, "title": "[YOK-51] Second orphan", "state": "CLOSED"},
        ])
        mock_gh_run.return_value = _completed(stdout=gh_json)
        rec = _run_hc(hc_gh_orphan_detection, conn)
        assert _result(rec).result == "WARN"
        assert "#50" in _result(rec).detail
        assert "#51" in _result(rec).detail


def _auth(repo: str):
    """Build a ProjectGithubAuth stub for resolver patches.

    Centralized so adding a field to ProjectGithubAuth doesn't require
    touching every test that stubs the resolver.
    """
    from yoke_core.domain.project_github_auth import ProjectGithubAuth
    return ProjectGithubAuth(project="yoke", repo=repo, token="t", env={"GH_TOKEN": "t"})
