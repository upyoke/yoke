"""Doctor HC tests (Bug language, undeployed-done, epic-task, size-bloat).

Other doctor_hc_meta_full tests live in sibling files.

Schema scaffolding shared via _doctor_hc_meta_full_test_helpers (private module).
Uses disposable Postgres test databases and mock subprocess for deterministic testing.
"""

from __future__ import annotations

import json
import re
import subprocess
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from yoke_core.engines.doctor import (
    DoctorArgs,
    RecordCollector,
    hc_empty_task_worktree,
    hc_epic_task_worktree,
    hc_epic_task_worktree_backfill,
    hc_orphan_epic_tasks,
    hc_size_bloat,
    hc_undeployed_done,
)

from yoke_core.engines._doctor_hc_meta_full_test_helpers import (
    _NOW_ISO,
    _args,
    _completed,
    _insert_deployment_flow,
    _insert_item,
    _iso_days_ago,
    _iso_minutes_ago,
    _make_conn,
    _result,
    _results,
    _run_hc,
    _seed_project,
)


class TestUndeployedDone:
    """Tests for hc_undeployed_done."""

    def test_pass_no_deploy_envs(self):
        """T1: PASS when project has no deployment environments."""
        conn = _make_conn()
        _seed_project(conn, "yoke")
        _insert_item(
            conn, 1, "Done", type="issue", status="done",
            created_at="2025-01-01T00:00:00Z",
            updated_at="2025-01-01T00:00:00Z",
        )
        rec = _run_hc(hc_undeployed_done, conn)
        assert _result(rec).result == "PASS"

    def test_warn_with_flows_undeployed(self):
        """T2: WARN when project has deployment flows and done items lack deployed_to."""
        conn = _make_conn()
        _seed_project(conn, "yoke")
        _insert_deployment_flow(conn, "f1")
        _insert_item(
            conn, 1, "Undeployed", type="issue", status="done",
            created_at="2025-01-01T00:00:00Z",
            updated_at="2025-01-01T00:00:00Z",
        )
        rec = _run_hc(hc_undeployed_done, conn)
        assert _result(rec).result == "WARN"
        assert "YOK-1" in _result(rec).detail

    def test_pass_all_deployed(self):
        """T3: PASS when all done items have deployed_to set."""
        conn = _make_conn()
        _seed_project(conn, "yoke")
        _insert_deployment_flow(conn, "f1")
        _insert_item(
            conn, 1, "Deployed", type="issue", status="done",
            deployed_to="local",
            created_at="2025-01-01T00:00:00Z",
            updated_at="2025-01-01T00:00:00Z",
        )
        rec = _run_hc(hc_undeployed_done, conn)
        assert _result(rec).result == "PASS"

    def test_per_project_scoping(self):
        """T5: Only flags projects with deployment flows."""
        conn = _make_conn()
        _seed_project(conn, "yoke")
        _seed_project(conn, "buzz")
        _insert_deployment_flow(conn, "f1", project="buzz")
        _insert_item(
            conn, 1, "Buzz done", project="buzz", type="issue", status="done",
            created_at="2025-01-01T00:00:00Z",
            updated_at="2025-01-01T00:00:00Z",
        )
        _insert_item(
            conn, 2, "Yoke done", type="issue", status="done",
            created_at="2025-01-01T00:00:00Z",
            updated_at="2025-01-01T00:00:00Z",
        )
        rec = _run_hc(hc_undeployed_done, conn)
        assert _result(rec).result == "WARN"
        assert "YOK-1" in _result(rec).detail
        assert "YOK-2" not in _result(rec).detail


class TestEpicTaskWorktree:
    """Tests for hc_epic_task_worktree."""

    def test_pass_all_have_worktree(self):
        """T1: PASS when all tasks have worktree populated."""
        conn = _make_conn()
        conn.execute(
            "INSERT INTO items (id, title, type, status) "
            "VALUES (1, 'Epic', 'epic', 'implementing')"
        )
        conn.execute(
            "INSERT INTO epic_tasks (id, epic_id, task_num, title, worktree, status) "
            "VALUES (1, 1, 1, 'Task', 'YOK-1', 'implementing')"
        )
        rec = _run_hc(hc_epic_task_worktree, conn)
        assert _result(rec).result == "PASS"

    def test_warn_null_worktree(self):
        """T2: WARN when tasks have NULL worktree."""
        conn = _make_conn()
        conn.execute(
            "INSERT INTO items (id, title, type, status) "
            "VALUES (1, 'Epic', 'epic', 'implementing')"
        )
        conn.execute(
            "INSERT INTO epic_tasks (id, epic_id, task_num, title, worktree, status) "
            "VALUES (1, 1, 1, 'Task', NULL, 'implementing')"
        )
        rec = _run_hc(hc_epic_task_worktree, conn)
        assert _result(rec).result == "WARN"


class TestEpicTaskWorktreeBackfill:
    """Tests for hc_epic_task_worktree_backfill."""

    def test_empty_worktree_warns(self):
        """Warn when epic tasks have empty worktree."""
        conn = _make_conn()
        conn.execute(
            "INSERT INTO items (id, title, type, status) "
            "VALUES (100, 'Test Epic', 'epic', 'implementing')"
        )
        conn.execute(
            "INSERT INTO epic_tasks (epic_id, task_num, title, status) "
            "VALUES (100, 1, 'Task 1', 'implementing')"
        )
        rec = _run_hc(hc_epic_task_worktree_backfill, conn)
        assert _result(rec).result == "WARN"
        assert "task 1" in _result(rec).detail

    def test_all_tasks_have_worktree_passes(self):
        conn = _make_conn()
        conn.execute(
            "INSERT INTO items (id, title, type, status) "
            "VALUES (100, 'Test Epic', 'epic', 'implementing')"
        )
        conn.execute(
            "INSERT INTO epic_tasks (epic_id, task_num, title, status, worktree) "
            "VALUES (100, 1, 'Task 1', 'implementing', 'YOK-100')"
        )
        rec = _run_hc(hc_epic_task_worktree_backfill, conn)
        assert _result(rec).result == "PASS"


class TestEmptyTaskWorktree:
    """Tests for hc_empty_task_worktree."""

    def test_pass_when_no_active_tasks(self):
        conn = _make_conn()
        rec = _run_hc(hc_empty_task_worktree, conn)
        assert _result(rec).result == "PASS"


class TestOrphanEpicTasks:
    """Tests for hc_orphan_epic_tasks."""

    def test_pass_all_have_parent(self):
        conn = _make_conn()
        conn.execute("INSERT INTO items (id, title) VALUES (1, 'Epic')")
        conn.execute(
            "INSERT INTO epic_tasks (id, epic_id, task_num, title) "
            "VALUES (1, 1, 1, 'Task')"
        )
        rec = _run_hc(hc_orphan_epic_tasks, conn)
        assert _result(rec).result == "PASS"

    def test_warn_orphan_task(self):
        conn = _make_conn()
        conn.execute(
            "INSERT INTO epic_tasks (id, epic_id, task_num, title) "
            "VALUES (1, 999, 1, 'Orphan task')"
        )
        rec = _run_hc(hc_orphan_epic_tasks, conn)
        assert _result(rec).result == "WARN"


class TestSizeBloat:
    """Tests for hc_size_bloat."""

    @patch("yoke_core.engines.doctor_report._resolve_repo_root", return_value=None)
    def test_pass_no_repo_root(self, mock_root):
        """Pass when no repo root found."""
        rec = _run_hc(hc_size_bloat)
        assert _result(rec).result == "PASS"

    @patch("yoke_core.engines.doctor_report._resolve_repo_root", return_value="/fake/repo")
    @patch("yoke_core.engines.doctor_report._run")
    def test_pass_small_repo(self, mock_run, mock_root):
        """Pass when DB and git are small."""
        mock_run.return_value = _completed(stdout="1000\t/fake/repo/.git\n")
        with patch.object(Path, "is_file", return_value=False), \
             patch.object(Path, "is_dir", return_value=False):
            rec = _run_hc(hc_size_bloat)
        assert _result(rec).result == "PASS"
