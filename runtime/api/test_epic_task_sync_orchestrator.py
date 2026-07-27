"""Tests for the high-level ``sync_epic_tasks`` orchestrator.

The per-task sync helpers live in ``runtime/api/test_epic_task_sync.py``;
backfill helpers and dependency-list parsing live in
``runtime/api/test_epic_task_sync_backfill.py``.

Tests mock the typed REST surfaces (``github_rest.*``) and the
canonical dedup helper directly. Yoke does NOT use the ``gh`` CLI.
"""

from __future__ import annotations

import io
from unittest.mock import patch

from runtime.api.conftest import insert_epic_task, insert_item
from yoke_core.domain import epic_task_sync

from runtime.api.epic_task_sync_orchestrator_test_support import (
    _mock_yoke_root as _mock_yoke_root,
    _stub_project_github_auth as _stub_project_github_auth,
    _stub_typed_rest_surfaces as _stub_typed_rest_surfaces,
    db as db,
)


class TestSyncEpicTasks:
    def test_sync_creates_epic_and_task_issues(self, db):
        insert_item(
            db,
            id=10,
            workflow_id="epic",
            status="implementing",
            project="externalwebapp",
            spec="Epic body here",
        )
        insert_epic_task(
            db,
            epic_id="10",
            task_num=1,
            title="First task",
            status="planned",
            body="Task 1 body",
        )
        insert_epic_task(
            db,
            epic_id="10",
            task_num=2,
            title="Second task",
            status="planned",
            body="Task 2 body",
        )
        stdout = io.StringIO()
        stderr = io.StringIO()

        rc = epic_task_sync.sync_epic_tasks(
            "YOK-10",
            conn=db,
            stdout=stdout,
            stderr=stderr,
        )

        assert rc == 0
        output = stdout.getvalue()
        assert "Sync complete" in output
        assert "2 created" in output

        row1 = db.execute(
            "SELECT t.github_issue, iw.branch FROM epic_tasks t "
            "LEFT JOIN item_worktrees iw ON iw.id=t.item_worktree_id "
            "WHERE t.epic_id='10' AND t.task_num=1"
        ).fetchone()
        assert row1 is not None
        assert row1[0] is not None
        assert row1[0].startswith("#")
        assert row1[1] == "YOK-10"

        row2 = db.execute(
            "SELECT github_issue FROM epic_tasks WHERE epic_id='10' AND task_num=2"
        ).fetchone()
        assert row2 is not None
        assert row2[0] is not None

    def test_sync_without_conn_uses_backend_connect(self, db):
        insert_item(
            db,
            id=10,
            workflow_id="epic",
            status="implementing",
            project="externalwebapp",
            spec="Epic body here",
        )
        insert_epic_task(
            db,
            epic_id="10",
            task_num=1,
            title="First task",
            status="planned",
            body="Task 1 body",
        )
        stdout = io.StringIO()
        stderr = io.StringIO()

        with (
            patch(
                "yoke_core.domain.epic_task_sync_github_orchestrator._connect_db",
                return_value=db,
            ) as open_conn,
            patch(
                "yoke_core.domain.epic_task_sync._db_path",
                side_effect=AssertionError("path resolver must not be used for sync"),
            ),
        ):
            rc = epic_task_sync.sync_epic_tasks(
                "YOK-10",
                stdout=stdout,
                stderr=stderr,
            )

        assert rc == 0
        open_conn.assert_called_once_with()
        assert "Sync complete" in stdout.getvalue()

    def test_sync_skips_already_synced_tasks(self, db):
        insert_item(
            db,
            id=10,
            workflow_id="epic",
            status="implementing",
            project="externalwebapp",
            spec="Epic body",
        )
        insert_epic_task(
            db,
            epic_id="10",
            task_num=1,
            title="Already synced",
            status="implementing",
            github_issue="#50",
            worktree="custom-synced",
        )
        insert_epic_task(
            db,
            epic_id="10",
            task_num=2,
            title="Not yet synced",
            status="planned",
            body="Task 2 body",
        )
        stdout = io.StringIO()

        rc = epic_task_sync.sync_epic_tasks("YOK-10", conn=db, stdout=stdout)

        assert rc == 0
        output = stdout.getvalue()
        assert "Skipping task 001 (already synced)" in output
        assert "1 created, 1 skipped" in output

        chains = db.execute(
            "SELECT iw.branch, c.queue FROM epic_dispatch_chains c "
            "JOIN item_worktrees iw ON iw.id=c.item_worktree_id "
            "WHERE c.epic_id='10'"
        ).fetchall()
        assert {row[0]: row[1] for row in chains} == {
            "YOK-10": '["002"]',
            "custom-synced": '["001"]',
        }

    def test_sync_dry_run_skips_github(self, db):
        insert_item(
            db, id=10, workflow_id="epic", status="implementing", project="externalwebapp"
        )
        insert_epic_task(
            db, epic_id="10", task_num=1, title="Task one", status="planned"
        )
        stdout = io.StringIO()

        with patch(
            "yoke_core.domain.epic_task_sync_github._is_dry_run", return_value=True
        ):
            rc = epic_task_sync.sync_epic_tasks("YOK-10", conn=db, stdout=stdout)

        assert rc == 0
        output = stdout.getvalue()
        assert "[DRY-RUN]" in output

    def test_sync_preserves_explicit_task_worktree(self, db):
        """Architect/refine worktree assignments are the dispatch source of truth."""
        insert_item(
            db,
            id=10,
            workflow_id="epic",
            status="implementing",
            project="externalwebapp",
            spec="body",
        )
        insert_epic_task(
            db,
            epic_id="10",
            task_num=1,
            title="Task",
            status="planned",
            worktree="custom-branch",
        )
        stdout = io.StringIO()

        rc = epic_task_sync.sync_epic_tasks("YOK-10", conn=db, stdout=stdout)

        assert rc == 0
        row = db.execute(
            "SELECT iw.branch FROM epic_tasks t "
            "JOIN item_worktrees iw ON iw.id=t.item_worktree_id "
            "WHERE t.epic_id='10' AND t.task_num=1"
        ).fetchone()
        assert row[0] == "custom-branch"

        chains = db.execute(
            "SELECT iw.branch, c.queue FROM epic_dispatch_chains c "
            "JOIN item_worktrees iw ON iw.id=c.item_worktree_id "
            "WHERE c.epic_id='10'"
        ).fetchall()
        assert [(row[0], row[1]) for row in chains] == [("custom-branch", '["001"]')]

    def test_sync_defaults_unlinked_task_to_parent_lane(self, db):
        """Unlinked tasks get the parent worker-lane fallback."""
        insert_item(
            db,
            id=10,
            workflow_id="epic",
            status="implementing",
            project="externalwebapp",
            spec="body",
        )
        insert_epic_task(db, epic_id="10", task_num=1, title="Task", status="planned")
        stdout = io.StringIO()
        stderr = io.StringIO()

        rc = epic_task_sync.sync_epic_tasks(
            "YOK-10",
            conn=db,
            stdout=stdout,
            stderr=stderr,
        )

        assert rc == 0
        row = db.execute(
            "SELECT iw.branch FROM epic_tasks t "
            "JOIN item_worktrees iw ON iw.id=t.item_worktree_id "
            "WHERE t.epic_id='10' AND t.task_num=1"
        ).fetchone()
        assert row[0] == "YOK-10"
        assert "defaulting to YOK-10" in stderr.getvalue()

    def test_main_sync_routing(self, capsys):
        """CLI 'sync' mode routes to sync_epic_tasks."""
        with patch(
            "yoke_core.domain.epic_task_sync_github_core.sync_epic_tasks",
            return_value=0,
        ) as mock:
            rc = epic_task_sync.main(["sync", "YOK-10"])
        assert rc == 0
        mock.assert_called_once_with("YOK-10", "")

    def test_main_sync_usage(self, capsys):
        rc = epic_task_sync.main(["sync"])
        captured = capsys.readouterr()
        assert rc == 1
        assert epic_task_sync.SYNC_USAGE in captured.err
