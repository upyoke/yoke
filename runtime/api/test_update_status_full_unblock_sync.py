"""Pytest behavioral tests for update_status: auto-unblock and GitHub sync (labels + checkbox)."""

from __future__ import annotations

import os
import textwrap

import pytest

from runtime.api.update_status_full_test_helpers import UpdateStatusEnv


@pytest.fixture
def env(tmp_path):
    e = UpdateStatusEnv(tmp_path, f"test-update-status-{os.getpid()}")
    try:
        yield e
    finally:
        e.close()


class TestAutoUnblock:
    """Tests 23, 29, 30 — blocked tasks auto-unblock on dependency completion."""

    def _setup_blocked_pair(self, env):
        env.exec_sql("""
            INSERT INTO epic_tasks
                (epic_id, task_num, title, worktree, status, dispatch_attempts,
                 dependencies, github_issue)
            VALUES
                (42, 1, 'First task', 'feature/test', 'implementing', 1, '', '#100'),
                (42, 2, 'Blocked task', 'feature/test', 'blocked', 0, '001', '#101');
        """)
        env.init_git()

    def test_auto_unblock_from_db(self, env):
        """TEST 23: completing task 1 auto-unblocks task 2."""
        self._setup_blocked_pair(env)
        r = env.run("42", "001", "done", extra_env={"YOKE_TASK_DONE_VERIFIED": "1"})
        assert r.returncode == 0
        assert env.query(
            "SELECT status FROM epic_tasks WHERE epic_id=42 AND task_num=2"
        ) == "planned"
        assert "Auto-unblocking" in r.stderr or "Auto-unblocking" in r.stdout

    def test_auto_unblock_on_done(self, env):
        """TEST 29: auto-unblock triggers specifically on done status."""
        self._setup_blocked_pair(env)
        r = env.run("42", "001", "done", extra_env={"YOKE_TASK_DONE_VERIFIED": "1"})
        assert r.returncode == 0
        assert env.query(
            "SELECT status FROM epic_tasks WHERE epic_id=42 AND task_num=2"
        ) == "planned"

    def test_auto_unblock_on_reviewed_implementation(self, env):
        """TEST 30: auto-unblock triggers on reviewed-implementation."""
        self._setup_blocked_pair(env)
        r = env.run("42", "001", "reviewed-implementation")
        assert r.returncode == 0
        assert env.query(
            "SELECT status FROM epic_tasks WHERE epic_id=42 AND task_num=2"
        ) == "planned"


class TestGitHubSync:
    """Tests 24, 25 — label swap and checkbox update via DB-native calls."""

    def test_github_label_swap(self, env):
        """TEST 24: REST POST adds the new status:implementing label + comment."""
        env.insert_task("planned")
        env.init_git()
        r = env.run("42", "003", "implementing")
        assert r.returncode == 0
        log = env.gh_log.read_text()
        # POST /labels (label-create idempotent) + POST /issues/100/labels.
        assert "POST /repos/upyoke/yoke/issues/100/labels" in log
        # POST /issues/100/comments for the status-change comment.
        assert "POST /repos/upyoke/yoke/issues/100/comments" in log

    def test_checkbox_from_db(self, env):
        """TEST 25: REST GET parent issue body when task transitions to done.

        Seeds the parent-body GET response with a checkbox line so the
        ``replace`` find-and-flip logic exercises the PATCH writeback.
        """
        import json
        env.exec_sql("""
            UPDATE items
            SET github_issue = '#200',
                status = 'implementing',
                updated_at = '2026-01-01'
            WHERE id = 42;
        """)
        env.insert_task("reviewed-implementation")
        env.init_git()

        # Seed the parent-issue GET response with the checkbox line.
        rest_dir = env.tmp / "rest-fakes"
        rest_dir.mkdir(exist_ok=True)
        (rest_dir / "GET_repos_upyoke_yoke_issues_200.json").write_text(
            json.dumps({
                "status": 200,
                "body": {
                    "number": 200,
                    "body": "- [ ] #100 Test task\n",
                    "state": "open",
                },
            }),
        )

        r = env.run("42", "003", "done", extra_env={"YOKE_TASK_DONE_VERIFIED": "1"})
        assert r.returncode == 0
        log = env.gh_log.read_text()
        # GET parent issue body via REST.
        assert "GET /repos/upyoke/yoke/issues/200" in log
