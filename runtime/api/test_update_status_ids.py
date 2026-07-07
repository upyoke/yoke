"""ID normalization and DB-native CRUD tests for update_status.

Covers YOK-N ref resolution, DB-native task status updates, history insertion,
dispatch_attempts increment, and done-guard behavior.
"""

from __future__ import annotations

import os

import pytest

from runtime.api.update_status_full_test_helpers import (
    TEST_EPIC_ID,
    TEST_EPIC_REF,
    UpdateStatusEnv,
)


@pytest.fixture
def env(tmp_path):
    """Provide a fresh UpdateStatusEnv per test."""
    e = UpdateStatusEnv(tmp_path, f"test-update-status-{os.getpid()}")
    try:
        yield e
    finally:
        e.close()


# ===================================================================
# DB-native CRUD
# ===================================================================

class TestDBNative:
    """Tests 19, 19b, 20, 21 — DB updates, YOK-N ref, history, dispatch_attempts."""

    def test_db_native_update(self, env):
        """TEST 19: DB-native interface updates epic_tasks status."""
        env.insert_task("planned")
        env.init_git()
        r = env.run("42", "003", "implementing", "Started")
        assert r.returncode == 0
        assert env.query(
            "SELECT status FROM epic_tasks WHERE epic_id=42 AND task_num=3"
        ) == "implementing"

    def test_yok_n_ref_resolves(self, env):
        """TEST 19b: YOK-N epic ref resolves to integer."""
        env.insert_task("planned")
        env.init_git()
        r = env.run(TEST_EPIC_REF, "003", "implementing", "From YOK ref")
        assert r.returncode == 0
        assert env.query(
            f"SELECT status FROM epic_tasks WHERE epic_id={TEST_EPIC_ID} AND task_num=3"
        ) == "implementing"

    def test_history_insert(self, env):
        """TEST 20: TaskStatusChanged event inserted in epic_task_history."""
        env.insert_task("planned")
        env.init_git()
        r = env.run("42", "003", "implementing", "Starting work")
        assert r.returncode == 0
        count = env.query_int(
            "SELECT COUNT(*) FROM epic_task_history WHERE epic_id=42 AND task_num=3"
        )
        assert count == 1
        assert env.query(
            "SELECT from_status FROM epic_task_history WHERE epic_id=42 AND task_num=3"
        ) == "planned"
        assert env.query(
            "SELECT to_status FROM epic_task_history WHERE epic_id=42 AND task_num=3"
        ) == "implementing"
        assert env.query(
            "SELECT note FROM epic_task_history WHERE epic_id=42 AND task_num=3"
        ) == "Starting work"

    def test_dispatch_attempts_increment(self, env):
        """TEST 21: dispatch_attempts incremented on implementing, not on done."""
        env.insert_task("planned", dispatch_attempts=1)
        env.init_git()
        r = env.run("42", "003", "implementing")
        assert r.returncode == 0
        assert env.query_int(
            "SELECT dispatch_attempts FROM epic_tasks WHERE epic_id=42 AND task_num=3"
        ) == 2
        # Non-implementing transition should NOT increment
        env.run("42", "003", "done", extra_env={"YOKE_TASK_DONE_VERIFIED": "1"})
        assert env.query_int(
            "SELECT dispatch_attempts FROM epic_tasks WHERE epic_id=42 AND task_num=3"
        ) == 2


# ===================================================================
# Done guard
# ===================================================================

class TestDoneGuard:
    """Task done is rejected without YOKE_TASK_DONE_VERIFIED."""

    def test_done_rejected_without_verified(self, env):
        """Exit 4 without YOKE_TASK_DONE_VERIFIED; success with it."""
        env.insert_task("implementing")
        env.init_git()

        # Without verified context
        r = env.run("42", "003", "done")
        assert r.returncode == 4
        output = r.stdout + r.stderr
        assert "epic-task done requires merge-verified context" in output
        assert "merge-verified" in output
        assert env.query(
            "SELECT status FROM epic_tasks WHERE epic_id=42 AND task_num=3"
        ) == "implementing"

        # With verified context
        r2 = env.run("42", "003", "done", extra_env={"YOKE_TASK_DONE_VERIFIED": "1"})
        assert r2.returncode == 0
        assert env.query(
            "SELECT status FROM epic_tasks WHERE epic_id=42 AND task_num=3"
        ) == "done"
