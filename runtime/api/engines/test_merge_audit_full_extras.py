"""Merge order, summary counts, git helpers, and CLI tests for merge_audit.

Report-generation, warnings, and standalone-branch tests live in
test_merge_audit_full.py.
"""

from __future__ import annotations

import os
import subprocess
from unittest import mock

import pytest

from yoke_core.engines import merge_audit
from yoke_core.engines.merge_audit_test_schema import (
    apply_merge_audit_schema,
)
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


@pytest.fixture()
def tmp_db(tmp_path):
    """Backend-aware DB with the merge-audit tables; yields its path.

    ``merge_audit.generate_report`` reads through the backend factory, so the
    schema and seed must land in the same backend (the file on SQLite, the
    repointed per-test database on Postgres).
    """
    with init_test_db(tmp_path, apply_schema=apply_merge_audit_schema) as path:
        yield path


GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "test",
    "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "test",
    "GIT_COMMITTER_EMAIL": "t@t",
}


@pytest.fixture()
def fake_repo(tmp_path):
    """Create a fake git repo with main branch."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], capture_output=True, check=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "--allow-empty", "-m", "init"],
        capture_output=True, check=True, env=GIT_ENV,
    )
    subprocess.run(
        ["git", "-C", str(repo), "branch", "-M", "main"],
        capture_output=True, check=True,
    )
    return str(repo)


def _add_branch(repo: str, name: str, num_commits: int = 1) -> None:
    """Create a branch with commits ahead of main."""
    subprocess.run(
        ["git", "-C", repo, "checkout", "-b", name],
        capture_output=True, check=True,
    )
    for i in range(num_commits):
        subprocess.run(
            ["git", "-C", repo, "commit", "--allow-empty", "-m", f"work {i+1} on {name}"],
            capture_output=True, check=True, env=GIT_ENV,
        )
    subprocess.run(
        ["git", "-C", repo, "checkout", "main"],
        capture_output=True, check=True,
    )


def _env(tmp_db, fake_repo):
    return {"YOKE_DB": tmp_db, "MERGE_AUDIT_REPO_ROOT": fake_repo}


class TestMergeOrder:
    """Recommended merge order."""

    def test_recommended_merge_order(self, tmp_db, fake_repo):
        """Report includes recommended merge order."""
        conn = connect_test_db(tmp_db)
        conn.execute("INSERT INTO items (id, title, status) VALUES (600, 'Merge Order', 'implementing')")
        conn.execute(
            "INSERT INTO epic_tasks (epic_id, task_num, title, status, worktree) "
            "VALUES (600, 1, 'T1', 'done', 'YOK-600')"
        )
        conn.commit()
        conn.close()

        _add_branch(fake_repo, "YOK-600")

        with mock.patch.dict(os.environ, _env(tmp_db, fake_repo)):
            report = merge_audit.generate_report()

        assert "### Recommended Merge Order" in report
        assert "1. YOK-600" in report


class TestSummaryCounts:
    """Summary section verification."""

    def test_ready_branch_counted(self, tmp_db, fake_repo):
        """Ready branch (all tasks done) counted correctly."""
        conn = connect_test_db(tmp_db)
        conn.execute("INSERT INTO items (id, title, status) VALUES (700, 'Ready', 'implementing')")
        conn.execute(
            "INSERT INTO epic_tasks (epic_id, task_num, title, status, worktree) "
            "VALUES (700, 1, 'T1', 'done', 'YOK-700')"
        )
        conn.commit()
        conn.close()

        _add_branch(fake_repo, "YOK-700")

        with mock.patch.dict(os.environ, _env(tmp_db, fake_repo)):
            report = merge_audit.generate_report()

        assert "Ready to merge: 1 branches" in report

    def test_blocked_branch_counted(self, tmp_db, fake_repo):
        """Blocked branch (incomplete tasks) counted correctly."""
        conn = connect_test_db(tmp_db)
        conn.execute("INSERT INTO items (id, title, status) VALUES (710, 'Blocked', 'implementing')")
        conn.execute(
            "INSERT INTO epic_tasks (epic_id, task_num, title, status, worktree) "
            "VALUES (710, 1, 'T1', 'done', 'YOK-710')"
        )
        conn.execute(
            "INSERT INTO epic_tasks (epic_id, task_num, title, status, worktree) "
            "VALUES (710, 2, 'T2', 'planned', 'YOK-710')"
        )
        conn.commit()
        conn.close()

        _add_branch(fake_repo, "YOK-710")

        with mock.patch.dict(os.environ, _env(tmp_db, fake_repo)):
            report = merge_audit.generate_report()

        assert "Blocked: 1 branches (incomplete tasks)" in report

    def test_conflicts_detected_zero(self, tmp_db, fake_repo):
        """Summary shows 'Conflicts detected: 0' when no conflicts."""
        conn = connect_test_db(tmp_db)
        conn.execute("INSERT INTO items (id, title, status) VALUES (720, 'NC', 'implementing')")
        conn.execute(
            "INSERT INTO epic_tasks (epic_id, task_num, title, status, worktree) "
            "VALUES (720, 1, 'T1', 'planned', 'YOK-720')"
        )
        conn.commit()
        conn.close()

        _add_branch(fake_repo, "YOK-720")

        with mock.patch.dict(os.environ, _env(tmp_db, fake_repo)):
            report = merge_audit.generate_report()

        assert "Conflicts detected: 0" in report


class TestGitHelpers:
    def test_branch_exists_false(self, fake_repo):
        assert not merge_audit._branch_exists(fake_repo, "nonexistent")

    def test_branch_exists_true(self, fake_repo):
        _add_branch(fake_repo, "test-branch")
        assert merge_audit._branch_exists(fake_repo, "test-branch")

    def test_commits_ahead(self, fake_repo):
        _add_branch(fake_repo, "ahead-branch")
        count = merge_audit._commits_ahead(fake_repo, "ahead-branch")
        assert count == 1

    def test_commits_ahead_multiple(self, fake_repo):
        _add_branch(fake_repo, "multi-ahead", num_commits=3)
        count = merge_audit._commits_ahead(fake_repo, "multi-ahead")
        assert count == 3

    def test_commits_ahead_nonexistent(self, fake_repo):
        count = merge_audit._commits_ahead(fake_repo, "nope")
        assert count == 0

    def test_list_sun_branches(self, fake_repo):
        _add_branch(fake_repo, "YOK-99")
        _add_branch(fake_repo, "YOK-100")
        _add_branch(fake_repo, "other-branch")
        branches = merge_audit._list_sun_branches(fake_repo)
        assert "YOK-99" in branches
        assert "YOK-100" in branches
        assert "other-branch" not in branches

    def test_list_sun_branches_empty(self, fake_repo):
        branches = merge_audit._list_sun_branches(fake_repo)
        assert branches == []

    def test_worktree_dirty_files_nonexistent(self, fake_repo):
        files = merge_audit._worktree_dirty_files("/nonexistent/path")
        assert files == []


class TestCLI:
    def test_exit_code_always_zero(self, tmp_db, fake_repo):
        """CLI exits 0 even when there are warnings."""
        conn = connect_test_db(tmp_db)
        conn.execute("INSERT INTO items (id, title, status) VALUES (800, 'Ex', 'implementing')")
        conn.execute(
            "INSERT INTO epic_tasks (epic_id, task_num, title, status, worktree) "
            "VALUES (800, 1, 'T1', 'planned', 'YOK-800')"
        )
        conn.commit()
        conn.close()

        _add_branch(fake_repo, "YOK-800")

        with mock.patch.dict(os.environ, _env(tmp_db, fake_repo)):
            report = merge_audit.generate_report(epic_filter=800)
        assert "# Merge Readiness Audit" in report

    def test_invalid_epic_id_via_main(self, fake_repo):
        """Invalid epic ID produces error and exit 1."""
        from io import StringIO as _SIO

        captured_err = _SIO()
        with mock.patch.dict(os.environ, {"MERGE_AUDIT_REPO_ROOT": fake_repo}):
            with mock.patch("sys.argv", ["merge_audit", "notanumber"]):
                with mock.patch("sys.stderr", captured_err):
                    with pytest.raises(SystemExit) as exc_info:
                        merge_audit.main()
                    assert exc_info.value.code == 1
        assert "invalid epic ID" in captured_err.getvalue()

    def test_sun_prefix_stripped(self, tmp_db, fake_repo):
        """YOK- prefix is stripped from epic ID argument."""
        with mock.patch.dict(os.environ, _env(tmp_db, fake_repo)):
            report = merge_audit.generate_report(epic_filter=42)
        assert "No unmerged branches found for epic 42." in report

    def test_no_args_runs_all(self, tmp_db, fake_repo):
        """No arguments runs all-epic audit."""
        with mock.patch.dict(os.environ, _env(tmp_db, fake_repo)):
            report = merge_audit.generate_report()
        assert "# Merge Readiness Audit" in report
