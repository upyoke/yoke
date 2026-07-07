"""Tests for yoke_core.engines.merge_audit report generation.

Git helper and CLI tests live in test_merge_audit_helpers.py.
"""

from __future__ import annotations

import sys
import os
import subprocess
from unittest import mock

import pytest

from yoke_core.engines import merge_audit
from yoke_core.engines.merge_audit_test_schema import (
    apply_merge_audit_schema,
)
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from runtime.api.source_pythonpath_test_helpers import SOURCE_PYTHONPATH


@pytest.fixture()
def tmp_db(tmp_path):
    """Backend-aware DB with the merge-audit tables; yields its path.

    ``merge_audit.generate_report`` reads through the backend factory, so the
    schema and seed must land in the same backend (the file on SQLite, the
    repointed per-test database on Postgres). The minimal schema is applied via
    :func:`apply_merge_audit_schema`.
    """
    with init_test_db(tmp_path, apply_schema=apply_merge_audit_schema) as path:
        yield path


@pytest.fixture()
def fake_repo(tmp_path):
    """Create a fake git repo with main branch."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], capture_output=True, check=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "--allow-empty", "-m", "init"],
        capture_output=True, check=True,
        env={**os.environ, "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "t@t",
             "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "t@t"},
    )
    # Rename default branch to main
    subprocess.run(
        ["git", "-C", str(repo), "branch", "-M", "main"],
        capture_output=True, check=True,
    )
    return str(repo)


def _add_branch(repo: str, name: str) -> None:
    """Create a branch with one commit ahead of main."""
    env = {**os.environ, "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "t@t"}
    subprocess.run(
        ["git", "-C", repo, "checkout", "-b", name],
        capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "-C", repo, "commit", "--allow-empty", "-m", f"work on {name}"],
        capture_output=True, check=True, env=env,
    )
    subprocess.run(
        ["git", "-C", repo, "checkout", "main"],
        capture_output=True, check=True,
    )


class TestGenerateReport:
    """Test report generation with mock git state."""

    def test_empty_report_no_epics(self, tmp_db, fake_repo):
        """Report with no epic tasks produces summary with zero branches."""
        with mock.patch.dict(os.environ, {"YOKE_DB": tmp_db, "MERGE_AUDIT_REPO_ROOT": fake_repo}):
            report = merge_audit.generate_report()

        assert "# Merge Readiness Audit" in report
        assert "Generated:" in report
        assert "No unmerged epic or standalone issue branches found." in report

    def test_epic_with_branches(self, tmp_db, fake_repo):
        """Report for an epic with unmerged branches includes branch table."""
        # Set up DB state
        conn = connect_test_db(tmp_db)
        conn.execute("INSERT INTO items (id, title, status) VALUES (100, 'Test Epic', 'implementing')")
        conn.execute(
            "INSERT INTO epic_tasks (epic_id, task_num, title, status, worktree) "
            "VALUES (100, 1, 'Task A', 'done', 'YOK-100')"
        )
        conn.execute(
            "INSERT INTO epic_tasks (epic_id, task_num, title, status, worktree) "
            "VALUES (100, 2, 'Task B', 'planned', 'YOK-100')"
        )
        conn.commit()
        conn.close()

        # Create branch in fake repo
        _add_branch(fake_repo, "YOK-100")

        with mock.patch.dict(os.environ, {"YOKE_DB": tmp_db, "MERGE_AUDIT_REPO_ROOT": fake_repo}):
            report = merge_audit.generate_report()

        assert "## Epic YOK-100: Test Epic" in report
        assert "Status: implementing | Tasks: 1/2 completed" in report
        assert "| YOK-100 |" in report
        assert "### Incomplete Tasks" in report
        assert "Task 2: Task B (status: planned)" in report

    def test_epic_filter(self, tmp_db, fake_repo):
        """Report scoped to a single epic only includes that epic."""
        conn = connect_test_db(tmp_db)
        conn.execute("INSERT INTO items (id, title, status) VALUES (200, 'Epic A', 'implementing')")
        conn.execute("INSERT INTO items (id, title, status) VALUES (201, 'Epic B', 'implementing')")
        conn.execute(
            "INSERT INTO epic_tasks (epic_id, task_num, title, status, worktree) "
            "VALUES (200, 1, 'Task X', 'planned', 'YOK-200')"
        )
        conn.execute(
            "INSERT INTO epic_tasks (epic_id, task_num, title, status, worktree) "
            "VALUES (201, 1, 'Task Y', 'planned', 'YOK-201')"
        )
        conn.commit()
        conn.close()

        _add_branch(fake_repo, "YOK-200")
        _add_branch(fake_repo, "YOK-201")

        with mock.patch.dict(os.environ, {"YOKE_DB": tmp_db, "MERGE_AUDIT_REPO_ROOT": fake_repo}):
            report = merge_audit.generate_report(epic_filter=200)

        assert "## Epic YOK-200: Epic A" in report
        assert "YOK-201" not in report

    def test_all_tasks_done_warning(self, tmp_db, fake_repo):
        """When all tasks are done but epic is not, shows warning."""
        conn = connect_test_db(tmp_db)
        conn.execute("INSERT INTO items (id, title, status) VALUES (300, 'Epic Done', 'implementing')")
        conn.execute(
            "INSERT INTO epic_tasks (epic_id, task_num, title, status, worktree) "
            "VALUES (300, 1, 'T1', 'done', 'YOK-300')"
        )
        conn.commit()
        conn.close()

        _add_branch(fake_repo, "YOK-300")

        with mock.patch.dict(os.environ, {"YOKE_DB": tmp_db, "MERGE_AUDIT_REPO_ROOT": fake_repo}):
            report = merge_audit.generate_report()

        assert "All tasks completed but item is `implementing`" in report
        assert "/yoke usher YOK-300" in report

    def test_simulation_missing_warning(self, tmp_db, fake_repo):
        """When integration simulation is missing, shows warning."""
        conn = connect_test_db(tmp_db)
        conn.execute("INSERT INTO items (id, title, status) VALUES (400, 'No Sim', 'implementing')")
        conn.execute(
            "INSERT INTO epic_tasks (epic_id, task_num, title, status, worktree) "
            "VALUES (400, 1, 'T1', 'planned', 'YOK-400')"
        )
        conn.commit()
        conn.close()

        _add_branch(fake_repo, "YOK-400")

        with mock.patch.dict(os.environ, {"YOKE_DB": tmp_db, "MERGE_AUDIT_REPO_ROOT": fake_repo}):
            report = merge_audit.generate_report()

        assert "Integration simulation missing" in report
        assert "/yoke simulate 400" in report

    def test_simulation_present(self, tmp_db, fake_repo):
        """When integration simulation exists, shows its result."""
        conn = connect_test_db(tmp_db)
        conn.execute("INSERT INTO items (id, title, status) VALUES (500, 'Has Sim', 'implementing')")
        conn.execute(
            "INSERT INTO epic_tasks (epic_id, task_num, title, status, worktree) "
            "VALUES (500, 1, 'T1', 'planned', 'YOK-500')"
        )
        conn.execute(
            "INSERT INTO epic_simulations (epic_id, phase, result) VALUES (500, 'integration', 'PASS')"
        )
        conn.commit()
        conn.close()

        _add_branch(fake_repo, "YOK-500")

        with mock.patch.dict(os.environ, {"YOKE_DB": tmp_db, "MERGE_AUDIT_REPO_ROOT": fake_repo}):
            report = merge_audit.generate_report()

        assert "Simulation: PASS" in report
        assert "Integration simulation missing" not in report

    def test_standalone_branches(self, tmp_db, fake_repo):
        """Standalone YOK-* branches with status done are reported."""
        conn = connect_test_db(tmp_db)
        conn.execute("INSERT INTO items (id, title, status) VALUES (50, 'Done Item', 'done')")
        conn.commit()
        conn.close()

        _add_branch(fake_repo, "YOK-50")

        with mock.patch.dict(os.environ, {"YOKE_DB": tmp_db, "MERGE_AUDIT_REPO_ROOT": fake_repo}):
            report = merge_audit.generate_report()

        assert "## Standalone Issue Branches" in report
        assert "YOK-50" in report
        assert "Done Item" in report

    def test_standalone_not_shown_with_filter(self, tmp_db, fake_repo):
        """Standalone branches are not shown when filtering by epic."""
        conn = connect_test_db(tmp_db)
        conn.execute("INSERT INTO items (id, title, status) VALUES (51, 'Done', 'done')")
        conn.commit()
        conn.close()

        _add_branch(fake_repo, "YOK-51")

        with mock.patch.dict(os.environ, {"YOKE_DB": tmp_db, "MERGE_AUDIT_REPO_ROOT": fake_repo}):
            report = merge_audit.generate_report(epic_filter=999)

        assert "Standalone Issue Branches" not in report

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

        with mock.patch.dict(os.environ, {"YOKE_DB": tmp_db, "MERGE_AUDIT_REPO_ROOT": fake_repo}):
            report = merge_audit.generate_report()

        assert "### Recommended Merge Order" in report
        assert "1. YOK-600" in report

    def test_summary_counts(self, tmp_db, fake_repo):
        """Summary section includes correct ready/blocked counts."""
        conn = connect_test_db(tmp_db)
        conn.execute("INSERT INTO items (id, title, status) VALUES (700, 'Counts', 'implementing')")
        conn.execute(
            "INSERT INTO epic_tasks (epic_id, task_num, title, status, worktree) "
            "VALUES (700, 1, 'T1', 'done', 'YOK-700')"
        )
        conn.execute(
            "INSERT INTO epic_tasks (epic_id, task_num, title, status, worktree) "
            "VALUES (700, 2, 'T2', 'planned', 'YOK-700')"
        )
        conn.commit()
        conn.close()

        _add_branch(fake_repo, "YOK-700")

        with mock.patch.dict(os.environ, {"YOKE_DB": tmp_db, "MERGE_AUDIT_REPO_ROOT": fake_repo}):
            report = merge_audit.generate_report()

        assert "## Summary" in report
        # 1 branch with incomplete tasks = blocked
        assert "Blocked: 1 branches (incomplete tasks)" in report

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

        result = subprocess.run(
            [sys.executable, "-m", "yoke_core.engines.merge_audit", "800"],
            capture_output=True, text=True,
            cwd=str(fake_repo),
            env={**os.environ, "YOKE_DB": tmp_db, "MERGE_AUDIT_REPO_ROOT": fake_repo,
                 "PYTHONPATH": SOURCE_PYTHONPATH},
        )
        assert result.returncode == 0
