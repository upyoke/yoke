"""Tests for service_client backlog-github relay and update-item validation."""

from __future__ import annotations

import json

from runtime.api.fixtures.file_test_db import connect_test_db
from runtime.api.test_service_client import _run_client
from runtime.api.test_service_client_delivery import mutation_db  # noqa: F401


class TestBacklogGithubRelay:
    def test_sync_item_rebuilds_board_on_success(self, monkeypatch, mutation_db):
        import yoke_core.api.service_client as service_client
        from yoke_core.domain import backlog
        from yoke_core.domain import backlog_github_sync

        rebuild_flags: list[bool] = []

        monkeypatch.setattr(backlog_github_sync, "sync_item", lambda *_args: 0)
        monkeypatch.setattr(
            backlog,
            "_maybe_rebuild_board",
            lambda rebuild_board, **_: rebuild_flags.append(rebuild_board),
        )

        rc = service_client.cmd_backlog_github(["sync-item", "7"])

        assert rc == 0
        assert rebuild_flags == [True]

    def test_non_sync_item_does_not_rebuild_board(self, monkeypatch, mutation_db):
        import yoke_core.api.service_client as service_client
        from yoke_core.domain import backlog
        from yoke_core.domain import backlog_github_sync

        rebuild_flags: list[bool] = []

        monkeypatch.setattr(backlog_github_sync, "sync_labels", lambda *_args: 0)
        monkeypatch.setattr(
            backlog,
            "_maybe_rebuild_board",
            lambda rebuild_board, **_: rebuild_flags.append(rebuild_board),
        )

        rc = service_client.cmd_backlog_github(["sync-labels", "7"])

        assert rc == 0
        assert rebuild_flags == []

    def test_update_title_too_long_rejected(self, mutation_db):
        """Title exceeding 100 chars should be rejected."""
        long_title = "B" * 101
        result = _run_client(
            ["update-item", "11", "--field", "title", "--value", long_title],
            db_path=mutation_db["db_path"],
        )
        assert result.returncode == 1
        data = json.loads(result.stdout.strip())
        assert data["success"] is False
        assert "100 characters" in data["error"]

    def test_update_missing_field_usage_error(self, mutation_db):
        """Missing --field should return exit code 2."""
        result = _run_client(
            ["update-item", "11", "--value", "active"],
            db_path=mutation_db["db_path"],
        )
        assert result.returncode == 2

    def test_update_missing_value_usage_error(self, mutation_db):
        """Missing --value should return exit code 2."""
        result = _run_client(
            ["update-item", "11", "--field", "status"],
            db_path=mutation_db["db_path"],
        )
        assert result.returncode == 2

    def test_update_epic_implementing_without_tasks_rejected(self, mutation_db):
        """Epic without tasks should not be allowed to transition to implementing."""
        # Create a taskless epic in planned status
        conn = connect_test_db(mutation_db["db_path"])
        conn.execute(
            """INSERT INTO items (id, title, type, status, priority, project_id,
                                  created_at, updated_at, source, frozen)
               VALUES (20, 'Taskless epic', 'epic', 'planned', 'medium', 1,
                       '2026-01-01', '2026-01-01', 'user', 0)"""
        )
        conn.commit()
        conn.close()

        result = _run_client(
            ["update-item", "20", "--field", "status", "--value", "implementing"],
            db_path=mutation_db["db_path"],
        )
        assert result.returncode == 1
        data = json.loads(result.stdout.strip())
        assert data["success"] is False
        assert data["error_code"] == "GATE_EPIC_TASKS"

    def test_update_epic_planned_without_tasks_allowed(self, mutation_db):
        """Epic without tasks should be allowed to transition to planned."""
        conn = connect_test_db(mutation_db["db_path"])
        conn.execute(
            """INSERT INTO items (id, title, type, status, priority, project_id,
                                  created_at, updated_at, source, frozen)
               VALUES (21, 'Taskless planned epic', 'epic', 'refining-plan', 'medium', 1,
                       '2026-01-01', '2026-01-01', 'user', 0)"""
        )
        conn.commit()
        conn.close()

        result = _run_client(
            ["update-item", "21", "--field", "status", "--value", "planned"],
            db_path=mutation_db["db_path"],
        )
        assert result.returncode == 0
        data = json.loads(result.stdout.strip())
        assert data["success"] is True

    def test_update_epic_implementing_with_tasks_allowed(self, mutation_db):
        """Epic WITH tasks should be allowed to transition to implementing."""
        conn = connect_test_db(mutation_db["db_path"])
        conn.execute(
            """INSERT INTO items (id, title, type, status, priority, project_id,
                                  created_at, updated_at, source, frozen)
               VALUES (22, 'Epic with tasks', 'epic', 'planned', 'medium', 1,
                       '2026-01-01', '2026-01-01', 'user', 0)"""
        )
        conn.execute(
            "INSERT INTO epic_tasks (epic_id, task_num, title, status) VALUES (22, 1, 'Task one', 'planned')"
        )
        conn.commit()
        conn.close()

        result = _run_client(
            ["update-item", "22", "--field", "status", "--value", "implementing"],
            db_path=mutation_db["db_path"],
        )
        assert result.returncode == 0
        data = json.loads(result.stdout.strip())
        assert data["success"] is True

    def test_update_issue_implementing_without_tasks_allowed(self, mutation_db):
        """Non-epic (issue) should reach implementing without needing epic tasks."""
        conn = connect_test_db(mutation_db["db_path"])
        conn.execute(
            """INSERT INTO items (id, title, type, status, priority, project_id,
                                  created_at, updated_at, source, frozen)
               VALUES (23, 'Plain issue', 'issue', 'refined-idea', 'medium', 1,
                       '2026-01-01', '2026-01-01', 'user', 0)"""
        )
        conn.commit()
        conn.close()

        result = _run_client(
            ["update-item", "23", "--field", "status", "--value", "implementing"],
            db_path=mutation_db["db_path"],
        )
        assert result.returncode == 0
        data = json.loads(result.stdout.strip())
        assert data["success"] is True

    def test_update_issue_to_retired_ready_rejected(self, mutation_db):
        """Retired status 'ready' should be rejected for issue items."""
        conn = connect_test_db(mutation_db["db_path"])
        conn.execute(
            """INSERT INTO items (id, title, type, status, priority, project_id,
                                  created_at, updated_at, source, frozen)
               VALUES (24, 'Issue wants ready', 'issue', 'refined-idea', 'medium', 1,
                       '2026-01-01', '2026-01-01', 'user', 0)"""
        )
        conn.commit()
        conn.close()

        result = _run_client(
            ["update-item", "24", "--field", "status", "--value", "ready"],
            db_path=mutation_db["db_path"],
        )
        assert result.returncode == 1
        data = json.loads(result.stdout.strip())
        assert data["success"] is False

    def test_update_frozen_field(self, mutation_db):
        """Updating frozen field returns success."""
        result = _run_client(
            ["update-item", "11", "--field", "frozen", "--value", "true"],
            db_path=mutation_db["db_path"],
        )
        assert result.returncode == 0
        data = json.loads(result.stdout.strip())
        assert data["success"] is True
        assert data["field_writes"]["frozen"] == "true"
