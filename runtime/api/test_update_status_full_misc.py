"""Pytest behavioral tests for update_status: invalid-status rejection and dispatch retry cycle."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from yoke_core.domain import update_status_helpers
from runtime.api.update_status_full_test_helpers import UpdateStatusEnv


@pytest.fixture
def env(tmp_path):
    e = UpdateStatusEnv(tmp_path, f"test-update-status-{os.getpid()}")
    yield e


class TestDBFailure:
    """Invalid status rejected, no false success."""

    def test_invalid_status_rejected(self, env):
        """CHECK constraint rejects invalid status; no GitHub ops run."""
        env.insert_task("implementing")
        env.init_git()
        r = env.run("42", "003", "passed")
        assert r.returncode != 0
        output = r.stdout + r.stderr
        assert "Status updated:" not in output
        assert "Error" in output
        assert env.query(
            "SELECT status FROM epic_tasks WHERE epic_id=42 AND task_num=3"
        ) == "implementing"
        log = env.gh_log.read_text()
        assert "issue comment" not in log
        assert "issue close" not in log


class TestDispatchRetry:
    """Dispatch_attempts incremented across retry cycles."""

    def test_retry_cycle(self, env):
        """Implementing->reviewing->implementing increments dispatch_attempts."""
        env.exec_sql("""
            INSERT INTO epic_tasks
                (epic_id, task_num, title, worktree, status, dispatch_attempts, github_issue)
            VALUES (42, 5, 'Retry task', 'feature/retry', 'planned', 0, '#200');
        """)
        env.insert_task("planned")
        env.init_git()

        env.run("42", "005", "implementing", "Initial dispatch")
        assert env.query_int(
            "SELECT dispatch_attempts FROM epic_tasks WHERE epic_id=42 AND task_num=5"
        ) == 1

        env.run("42", "005", "reviewing-implementation", "Engineer complete")
        assert env.query_int(
            "SELECT dispatch_attempts FROM epic_tasks WHERE epic_id=42 AND task_num=5"
        ) == 1

        env.run("42", "005", "implementing", "Retry 2 of 5")
        assert env.query_int(
            "SELECT dispatch_attempts FROM epic_tasks WHERE epic_id=42 AND task_num=5"
        ) == 2

        env.run("42", "005", "reviewing-implementation", "Engineer retry")
        env.run("42", "005", "implementing", "Retry 3 of 5")
        assert env.query_int(
            "SELECT dispatch_attempts FROM epic_tasks WHERE epic_id=42 AND task_num=5"
        ) == 3

        count = env.query_int(
            "SELECT COUNT(*) FROM epic_task_history WHERE epic_id=42 AND task_num=5"
        )
        assert count >= 3


class TestRuntimeRootResolution:
    """Helper path resolution should honor the active runtime state root."""

    def test_repo_root_prefers_yoke_root_env(self, env, monkeypatch):
        monkeypatch.setenv("YOKE_ROOT", str(env.root / ".yoke"))
        monkeypatch.chdir(env.root)

        assert update_status_helpers._repo_root() == Path(env.root)
