"""Doctor HC tests for worktree-health and stale-remote-branches checks.

Delegated-sync and gh-orphan-detection tests live in test_doctor_hc_git_full.py.
Wrong-repo/orphaned-active-items tests live in test_doctor_hc_git_full_repos.py.
Orphaned-gh-issues tests live in test_doctor_hc_git_full_orphans.py.

Schema scaffolding is shared via _doctor_hc_git_test_helpers (private module).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from yoke_core.engines._doctor_hc_git_test_helpers import (
    _completed,
    _insert_item,
    _make_conn,
    _result,
    _run_hc,
    _seed_project,
)
from yoke_core.engines.doctor import (
    DoctorArgs,
    RecordCollector,
    _should_run_hc,
    HEALTH_CHECKS,
    hc_stale_remote_branches,
    hc_worktree_health,
)


class TestWorktreeHealth:
    """Tests for hc_worktree_health."""

    @patch("yoke_core.engines.doctor_report._resolve_repo_root", return_value="/fake/repo")
    @patch("yoke_core.engines.doctor_report._run")
    def test_clean_done_item_passes(self, mock_run, mock_root):
        """T1: PASS state -- clean done item produces PASS."""
        mock_run.side_effect = [
            # git worktree list --porcelain
            _completed(stdout=(
                "worktree /fake/repo\n"
                "branch refs/heads/main\n"
                "\n"
            )),
            # git rev-parse --verify <branch> (branch does not exist)
            _completed(returncode=1, stdout=""),
        ]
        conn = _make_conn()
        conn.execute(
            "INSERT INTO items (id, title, type, status) "
            "VALUES (10, 'Done item', 'issue', 'done')"
        )
        with patch.object(Path, "is_dir", return_value=False):
            rec = _run_hc(hc_worktree_health, conn)
        assert _result(rec).result == "PASS"

    @patch("yoke_core.engines.doctor_report._resolve_repo_root", return_value="/fake/repo")
    @patch("yoke_core.engines.doctor_report._run")
    def test_stale_local_branch(self, mock_run, mock_root):
        """T2: Stale local branch for done item."""
        mock_run.side_effect = [
            # git worktree list --porcelain
            _completed(stdout=(
                "worktree /fake/repo\n"
                "branch refs/heads/main\n"
                "\n"
            )),
            # git rev-parse --verify <branch> (branch exists)
            _completed(returncode=0, stdout="abc123\n"),
        ]
        conn = _make_conn()
        conn.execute(
            "INSERT INTO items (id, title, type, status) "
            "VALUES (20, 'Done item', 'issue', 'done')"
        )
        with patch.object(Path, "is_dir", return_value=False):
            rec = _run_hc(hc_worktree_health, conn)
        assert _result(rec).result == "WARN"
        assert "Stale local branch" in _result(rec).detail
        assert "YOK-20" in _result(rec).detail

    @patch("yoke_core.engines.doctor_report._resolve_repo_root", return_value=None)
    @patch("yoke_core.engines.doctor_report._run")
    def test_dirty_worktree_warns(self, mock_run, mock_root):
        """T9: Dirty worktree detected via git worktree list."""
        mock_run.side_effect = [
            _completed(stdout=(
                "worktree /fake/repo\n"
                "branch refs/heads/main\n"
                "\n"
                "worktree /fake/wt/YOK-9999\n"
                "branch refs/heads/YOK-9999\n"
                "\n"
            )),
            _completed(stdout="M file.py\n"),  # dirty
        ]
        conn = _make_conn()
        conn.execute(
            "INSERT INTO items (id, title, type, status) "
            "VALUES (42, 'Active item', 'issue', 'implementing')"
        )
        with patch.object(Path, "is_dir", return_value=True):
            rec = _run_hc(hc_worktree_health, conn)
        assert _result(rec).result == "WARN"
        assert "uncommitted changes" in _result(rec).detail

    @patch("yoke_core.engines.doctor_report._resolve_repo_root", return_value="/fake/repo")
    @patch("yoke_core.engines.doctor_report._run")
    def test_non_done_items_excluded(self, mock_run, mock_root):
        """T7: Non-done items excluded -- active item with branch not flagged as stale."""
        mock_run.return_value = _completed(stdout=(
            "worktree /fake/repo\n"
            "branch refs/heads/main\n"
            "\n"
        ))
        conn = _make_conn()
        conn.execute(
            "INSERT INTO items (id, title, type, status) "
            "VALUES (70, 'Active item', 'issue', 'implementing')"
        )
        rec = _run_hc(hc_worktree_health, conn)
        detail = _result(rec).detail or ""
        assert "YOK-70" not in detail or _result(rec).result == "PASS"


class TestStaleRemoteBranches:
    """Tests for hc_stale_remote_branches."""

    @patch("yoke_core.engines.doctor_report._resolve_repo_root", return_value="/fake/repo")
    @patch("yoke_core.engines.doctor_report._run")
    def test_no_stale_branches_passes(self, mock_run, mock_root):
        """T1: PASS when no remote branches for done items."""
        conn = _make_conn()
        _seed_project(conn, "yoke")
        _insert_item(conn, 10, "Done item", type="issue", status="done")
        mock_run.side_effect = [
            _completed(stdout=""),  # ls-remote for yoke
            _completed(stdout=""),  # ls-remote for default
        ]
        rec = _run_hc(hc_stale_remote_branches, conn)
        assert _result(rec).result == "PASS"

    @patch("yoke_core.engines.doctor_report._resolve_repo_root", return_value="/fake/repo")
    @patch("yoke_core.engines.doctor_report._run")
    def test_stale_branch_warns(self, mock_run, mock_root):
        """T2: Stale remote branch YOK-N detected for done item."""
        conn = _make_conn()
        _seed_project(conn, "yoke")
        _insert_item(conn, 20, "Done item", type="issue", status="done")
        mock_run.side_effect = [
            _completed(stdout="abc123\trefs/heads/YOK-20\n"),
            _completed(stdout="abc123\trefs/heads/YOK-20\n"),
        ]
        rec = _run_hc(hc_stale_remote_branches, conn)
        assert _result(rec).result == "WARN"
        assert "YOK-20" in _result(rec).detail

    @patch("yoke_core.engines.doctor_report._resolve_repo_root", return_value="/fake/repo")
    @patch("yoke_core.engines.doctor_report._run")
    def test_active_item_not_flagged(self, mock_run, mock_root):
        """T3: Active item with remote branch NOT flagged."""
        conn = _make_conn()
        _seed_project(conn, "yoke")
        _insert_item(conn, 50, "Active item", type="issue", status="implementing")
        mock_run.side_effect = [
            _completed(stdout="abc123\trefs/heads/YOK-50\n"),
            _completed(stdout="abc123\trefs/heads/YOK-50\n"),
        ]
        rec = _run_hc(hc_stale_remote_branches, conn)
        detail = _result(rec).detail or ""
        assert "YOK-50" not in detail

    @patch("yoke_core.engines.doctor_report._resolve_repo_root", return_value="/fake/repo")
    @patch("yoke_core.engines.doctor_report._run")
    def test_cancelled_item_flagged(self, mock_run, mock_root):
        """T6: Cancelled item with remote branch IS flagged."""
        conn = _make_conn()
        _seed_project(conn, "yoke")
        _insert_item(conn, 60, "Cancelled", type="issue", status="cancelled")
        mock_run.side_effect = [
            _completed(stdout="abc123\trefs/heads/YOK-60\n"),
            _completed(stdout="abc123\trefs/heads/YOK-60\n"),
        ]
        rec = _run_hc(hc_stale_remote_branches, conn)
        assert _result(rec).result == "WARN"
        assert "YOK-60" in _result(rec).detail

    def test_quick_mode_skips(self):
        """T7: HC-stale-remote-branches skipped in --quick mode."""
        args = DoctorArgs(quick=True)
        assert not _should_run_hc("stale-remote-branches", args)

    def test_warn_severity_not_fail(self):
        """T9: HC-stale-remote-branches issues appear as WARN severity."""
        # Verified by the above tests that produce WARN, not FAIL
        slugs = {hc.slug for hc in HEALTH_CHECKS}
        assert "stale-remote-branches" in slugs
        hc = [h for h in HEALTH_CHECKS if h.slug == "stale-remote-branches"][0]
        assert hc.github_dependent
