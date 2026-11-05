"""Tests for the doctor engine: worktree, filesystem, and stale-branch HCs.

Git-state HCs (main-checkout, branch-divergence, uncaptured-discoveries,
orphaned-stashes, cross-project-commits) live in test_doctor_git.py.
GitHub-dependent HCs and registration tests live in test_doctor_git_github.py.

Tests use mock subprocess to avoid real git/gh calls.
"""

from __future__ import annotations

from runtime.api.engines.doctor_git_worktrees_test_support import (_args as _args, _make_conn as _make_conn, _run_hc as _run_hc)
from runtime.api.engines.doctor_git_github_test_support import (_make_completed as _make_completed)


from pathlib import Path
from unittest.mock import patch

from runtime.api.fixtures.backlog import insert_item_worktree
from yoke_core.engines.doctor import (
    hc_epic_task_worktree_backfill,
    hc_path_confabulation,
    hc_worktree_health,
)


class TestHcEpicTaskWorktreeBackfill:
    """Tests for hc_epic_task_worktree_backfill."""

    def test_empty_worktree_warns(self):
        conn = _make_conn()
        conn.execute(
            "INSERT INTO items (id, title, workflow_id, workflow_version_id, status) "
            "VALUES (100, 'Test Epic', 'epic', (SELECT current_version_id FROM workflows WHERE id='epic'), 'implementing')"
        )
        conn.execute(
            "INSERT INTO epic_tasks (epic_id, task_num, title, status) VALUES (100, 1, 'Task 1', 'pending')"
        )
        rec = _run_hc(hc_epic_task_worktree_backfill, conn)
        assert rec.results[0].result == "WARN"
        assert "task 1" in rec.results[0].detail

    def test_all_tasks_have_worktree_passes(self):
        conn = _make_conn()
        conn.execute(
            "INSERT INTO items (id, title, workflow_id, workflow_version_id, status) "
            "VALUES (100, 'Test Epic', 'epic', (SELECT current_version_id FROM workflows WHERE id='epic'), 'implementing')"
        )
        conn.execute(
            "INSERT INTO epic_tasks (epic_id, task_num, title, status, item_worktree_id) VALUES (100, 1, 'Task 1', 'pending', %s)",
            (
                insert_item_worktree(
                    conn, item_id=100, branch="YOK-100", lane_role="worker"
                )["id"],
            ),
        )
        rec = _run_hc(hc_epic_task_worktree_backfill, conn)
        assert rec.results[0].result == "PASS"


class TestHcWorktreeHealth:
    """Tests for hc_worktree_health."""

    @patch(
        "yoke_core.engines.doctor_report._resolve_repo_root", return_value="/fake/repo"
    )
    @patch("yoke_core.engines.doctor_report._run")
    def test_clean_worktrees_pass(self, mock_run, mock_root):
        mock_run.side_effect = [
            _make_completed(stdout=("worktree /fake/repo\nbranch refs/heads/main\n\n")),
            _make_completed(stdout="main\n"),  # one local branch inventory
            # The deploy-run driver pass re-lists worktrees; none here.
            _make_completed(stdout=""),
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
            _make_completed(
                stdout=(
                    "worktree /fake/repo\nbranch refs/heads/main\n\nworktree /fake/wt/YOK-9999\nbranch refs/heads/YOK-9999\n\n"
                )
            ),
            _make_completed(stdout="main\nYOK-9999\n"),
            # Porcelain status is two state columns then the path, so the
            # modified-in-worktree line leads with a space. The reason the
            # HC now prints names the file, which a malformed line truncates.
            _make_completed(stdout=" M file.py\n"),
        ]
        conn = _make_conn()
        conn.execute(
            "INSERT INTO items (id, title, workflow_id, workflow_version_id, status) "
            "VALUES (42, 'Test', 'issue', (SELECT current_version_id FROM workflows WHERE id='issue'), 'implementing')"
        )
        with patch.object(Path, "is_dir", return_value=True):
            rec = _run_hc(hc_worktree_health, conn)
        assert rec.results[0].result == "WARN"
        assert (
            "holds content cleanup preserves (unignored changes present: file.py)"
            in rec.results[0].detail
        )


class TestHcPathConfabulation:
    """Tests for hc_path_confabulation."""

    @patch(
        "yoke_core.engines.doctor_report._resolve_repo_root", return_value="/fake/repo"
    )
    def test_no_confabulation_passes(self, mock_root):
        conn = _make_conn()
        rec = _run_hc(hc_path_confabulation, conn)
        assert rec.results[0].result == "PASS"

    @patch(
        "yoke_core.engines.doctor_report._resolve_repo_root", return_value="/fake/repo"
    )
    def test_confabulated_ouroboros_entry_warns(self, mock_root):
        conn = _make_conn()
        conn.execute(
            "INSERT INTO ouroboros_entries (id, body) VALUES (1, 'Found issue in ouraboros/patterns.md')"
        )
        rec = _run_hc(hc_path_confabulation, conn)
        assert rec.results[0].result == "WARN"
        assert "ouroboros_entries" in rec.results[0].detail

    @patch(
        "yoke_core.engines.doctor_report._resolve_repo_root", return_value="/fake/repo"
    )
    def test_suppressed_line_passes(self, mock_root):
        conn = _make_conn()
        conn.execute(
            "INSERT INTO ouroboros_entries (id, body) VALUES (1, 'The word ouraboros here <!-- not-confabulated -->')"
        )
        rec = _run_hc(hc_path_confabulation, conn)
        assert rec.results[0].result == "PASS"
