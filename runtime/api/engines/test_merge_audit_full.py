"""Behavioural tests for merge_audit report generation, warnings, and standalone
branches.

Merge-order, summary-counts, git-helper, and CLI tests live in
test_merge_audit_full_extras.py.
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


class TestGenerateReport:
    """Full report generation with mocked git state."""

    def test_empty_report_no_epics(self, tmp_db, fake_repo):
        """Report with no epic tasks shows no unmerged branches."""
        with mock.patch.dict(os.environ, _env(tmp_db, fake_repo)):
            report = merge_audit.generate_report()
        assert "# Merge Readiness Audit" in report
        assert "Generated:" in report
        assert "No unmerged epic or standalone issue branches found." in report

    def test_epic_with_branches_includes_branch_table(self, tmp_db, fake_repo):
        """Report includes branch table for epics with unmerged branches."""
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

        _add_branch(fake_repo, "YOK-100")

        with mock.patch.dict(os.environ, _env(tmp_db, fake_repo)):
            report = merge_audit.generate_report()

        assert "## Epic YOK-100: Test Epic" in report
        assert "Status: implementing | Tasks: 1/2 completed" in report
        assert "| YOK-100 |" in report
        assert "### Incomplete Tasks" in report
        assert "Task 2: Task B (status: planned)" in report

    def test_multiple_worktrees_per_epic(self, tmp_db, fake_repo):
        """Report handles epic with multiple distinct worktree branches."""
        conn = connect_test_db(tmp_db)
        conn.execute("INSERT INTO items (id, title, status) VALUES (150, 'Multi-WT', 'implementing')")
        conn.execute(
            "INSERT INTO epic_tasks (epic_id, task_num, title, status, worktree) "
            "VALUES (150, 1, 'T1', 'done', 'YOK-150')"
        )
        conn.execute(
            "INSERT INTO epic_tasks (epic_id, task_num, title, status, worktree) "
            "VALUES (150, 2, 'T2', 'planned', 'YOK-150-b')"
        )
        conn.commit()
        conn.close()

        _add_branch(fake_repo, "YOK-150")
        _add_branch(fake_repo, "YOK-150-b")

        with mock.patch.dict(os.environ, _env(tmp_db, fake_repo)):
            report = merge_audit.generate_report()

        assert "YOK-150" in report
        assert "YOK-150-b" in report

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

        with mock.patch.dict(os.environ, _env(tmp_db, fake_repo)):
            report = merge_audit.generate_report(epic_filter=200)

        assert "## Epic YOK-200: Epic A" in report
        assert "YOK-201" not in report

    def test_no_branches_for_epic_filter(self, tmp_db, fake_repo):
        """Epic filter with no matching branches."""
        with mock.patch.dict(os.environ, _env(tmp_db, fake_repo)):
            report = merge_audit.generate_report(epic_filter=999)
        assert "No unmerged branches found for epic 999." in report


class TestWarnings:
    """Warning detection for merge readiness."""

    def test_all_tasks_done_warning(self, tmp_db, fake_repo):
        """All tasks done but item not done shows warning."""
        conn = connect_test_db(tmp_db)
        conn.execute("INSERT INTO items (id, title, status) VALUES (300, 'Epic Done', 'implementing')")
        conn.execute(
            "INSERT INTO epic_tasks (epic_id, task_num, title, status, worktree) "
            "VALUES (300, 1, 'T1', 'done', 'YOK-300')"
        )
        conn.commit()
        conn.close()

        _add_branch(fake_repo, "YOK-300")

        with mock.patch.dict(os.environ, _env(tmp_db, fake_repo)):
            report = merge_audit.generate_report()

        assert "All tasks completed but item is `implementing`" in report
        assert "/yoke usher YOK-300" in report

    def test_no_warning_when_item_is_done(self, tmp_db, fake_repo):
        """No warning when all tasks done AND item is done."""
        conn = connect_test_db(tmp_db)
        conn.execute("INSERT INTO items (id, title, status) VALUES (310, 'Done Done', 'done')")
        conn.execute(
            "INSERT INTO epic_tasks (epic_id, task_num, title, status, worktree) "
            "VALUES (310, 1, 'T1', 'done', 'YOK-310')"
        )
        conn.commit()
        conn.close()

        _add_branch(fake_repo, "YOK-310")

        with mock.patch.dict(os.environ, _env(tmp_db, fake_repo)):
            report = merge_audit.generate_report()

        assert "All tasks completed but item is" not in report

    def test_simulation_missing_warning(self, tmp_db, fake_repo):
        """Missing integration simulation shows warning."""
        conn = connect_test_db(tmp_db)
        conn.execute("INSERT INTO items (id, title, status) VALUES (400, 'No Sim', 'implementing')")
        conn.execute(
            "INSERT INTO epic_tasks (epic_id, task_num, title, status, worktree) "
            "VALUES (400, 1, 'T1', 'planned', 'YOK-400')"
        )
        conn.commit()
        conn.close()

        _add_branch(fake_repo, "YOK-400")

        with mock.patch.dict(os.environ, _env(tmp_db, fake_repo)):
            report = merge_audit.generate_report()

        assert "Integration simulation missing" in report
        assert "/yoke simulate 400" in report

    def test_simulation_present_no_warning(self, tmp_db, fake_repo):
        """Simulation present shows result, no missing warning."""
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

        with mock.patch.dict(os.environ, _env(tmp_db, fake_repo)):
            report = merge_audit.generate_report()

        assert "Simulation: PASS" in report
        assert "Integration simulation missing" not in report

    def test_simulation_fail_result_shown(self, tmp_db, fake_repo):
        """Failed simulation result displayed."""
        conn = connect_test_db(tmp_db)
        conn.execute("INSERT INTO items (id, title, status) VALUES (501, 'Fail Sim', 'implementing')")
        conn.execute(
            "INSERT INTO epic_tasks (epic_id, task_num, title, status, worktree) "
            "VALUES (501, 1, 'T1', 'planned', 'YOK-501')"
        )
        conn.execute(
            "INSERT INTO epic_simulations (epic_id, phase, result) VALUES (501, 'integration', 'FAIL')"
        )
        conn.commit()
        conn.close()

        _add_branch(fake_repo, "YOK-501")

        with mock.patch.dict(os.environ, _env(tmp_db, fake_repo)):
            report = merge_audit.generate_report()

        assert "Simulation: FAIL" in report


class TestStandaloneBranches:
    """Standalone YOK-* branch detection."""

    def test_standalone_branches_reported(self, tmp_db, fake_repo):
        """Standalone YOK-* branches with status done are reported."""
        conn = connect_test_db(tmp_db)
        conn.execute("INSERT INTO items (id, title, status) VALUES (50, 'Done Item', 'done')")
        conn.commit()
        conn.close()

        _add_branch(fake_repo, "YOK-50")

        with mock.patch.dict(os.environ, _env(tmp_db, fake_repo)):
            report = merge_audit.generate_report()

        assert "## Standalone Issue Branches" in report
        assert "YOK-50" in report
        assert "Done Item" in report

    def test_standalone_not_done_not_shown(self, tmp_db, fake_repo):
        """Standalone branches for non-done items are not shown."""
        conn = connect_test_db(tmp_db)
        conn.execute("INSERT INTO items (id, title, status) VALUES (51, 'Active', 'implementing')")
        conn.commit()
        conn.close()

        _add_branch(fake_repo, "YOK-51")

        with mock.patch.dict(os.environ, _env(tmp_db, fake_repo)):
            report = merge_audit.generate_report()

        assert "YOK-51" not in report or "Standalone" not in report

    def test_standalone_not_shown_with_filter(self, tmp_db, fake_repo):
        """Standalone branches are not shown when filtering by epic."""
        conn = connect_test_db(tmp_db)
        conn.execute("INSERT INTO items (id, title, status) VALUES (52, 'Done', 'done')")
        conn.commit()
        conn.close()

        _add_branch(fake_repo, "YOK-52")

        with mock.patch.dict(os.environ, _env(tmp_db, fake_repo)):
            report = merge_audit.generate_report(epic_filter=999)

        assert "Standalone Issue Branches" not in report
