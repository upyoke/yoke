# ruff: noqa: F811
"""Tests for service_client create-item mutation command.
Split from test_service_client.py. The companion update-item suite
lives in ``test_service_client_delivery_update.py``. The shared
``mutation_db`` fixture lives in
``test_service_client_delivery_test_helpers``.
"""

from __future__ import annotations

import json

from runtime.api.fixtures.file_test_db import connect_test_db
from runtime.api.test_service_client import _run_client

# Re-export the shared fixture for pytest discovery.
from runtime.api.test_service_client_delivery_test_helpers import (  # noqa: F401
    mutation_db,
)


# ---------------------------------------------------------------------------
# create-item tests task 3
# ---------------------------------------------------------------------------


class TestCreateItem:
    """Tests for create-item mutation command."""

    def test_create_success_returns_json(self, mutation_db):
        """Basic create with title and type returns success JSON."""
        result = _run_client(
            ["create-item", "--title", "New feature", "--type", "issue"],
            db_path=mutation_db["db_path"],
        )
        assert result.returncode == 0
        data = json.loads(result.stdout.strip())
        assert data["success"] is True
        assert data["field_writes"]["title"] == "New feature"
        assert data["field_writes"]["type"] == "issue"
        assert data["field_writes"]["status"] == "idea"
        assert data["field_writes"]["priority"] == "medium"
        assert "events" in data
        assert any(e["kind"] == "created" for e in data["events"])

    def test_create_with_all_options(self, mutation_db):
        """Create with all optional fields returns correct field_writes."""
        result = _run_client(
            ["create-item", "--title", "Epic item", "--type", "epic",
             "--priority", "high", "--project", "yoke",
             "--deployment-flow", "test-flow"],
            db_path=mutation_db["db_path"],
        )
        assert result.returncode == 0
        data = json.loads(result.stdout.strip())
        assert data["success"] is True
        assert data["field_writes"]["type"] == "epic"
        assert data["field_writes"]["priority"] == "high"
        assert data["field_writes"]["project"] == "yoke"
        assert data["field_writes"]["deployment_flow"] == "test-flow"
        assert [e["kind"] for e in data["events"]] == ["created"]

    def test_create_has_defaults(self, mutation_db):
        """Create result includes defaults dict."""
        result = _run_client(
            ["create-item", "--title", "Test", "--type", "issue"],
            db_path=mutation_db["db_path"],
        )
        assert result.returncode == 0
        data = json.loads(result.stdout.strip())
        assert "defaults" in data
        assert data["defaults"]["status"] == "idea"
        assert data["defaults"]["flow"] == "accelerated"

    def test_create_title_too_long_rejected(self, mutation_db):
        """Title exceeding 100 chars should be rejected."""
        long_title = "A" * 101
        result = _run_client(
            ["create-item", "--title", long_title, "--type", "issue"],
            db_path=mutation_db["db_path"],
        )
        assert result.returncode == 1
        data = json.loads(result.stdout.strip())
        assert data["success"] is False
        assert "100 characters" in data["error"]
        assert data["error_code"] == "VALIDATION_ERROR"

    def test_create_invalid_type_rejected(self, mutation_db):
        """Invalid item type should be rejected."""
        result = _run_client(
            ["create-item", "--title", "Test", "--type", "bogus"],
            db_path=mutation_db["db_path"],
        )
        assert result.returncode == 1
        data = json.loads(result.stdout.strip())
        assert data["success"] is False
        assert "Invalid type" in data["error"]

    def test_create_invalid_priority_rejected(self, mutation_db):
        """Invalid priority should be rejected."""
        result = _run_client(
            ["create-item", "--title", "Test", "--type", "issue",
             "--priority", "critical"],
            db_path=mutation_db["db_path"],
        )
        assert result.returncode == 1
        data = json.loads(result.stdout.strip())
        assert data["success"] is False
        assert "Invalid priority" in data["error"]

    def test_create_missing_title_usage_error(self):
        """Missing --title should return exit code 2."""
        result = _run_client(["create-item", "--type", "issue"])
        assert result.returncode == 2

    def test_create_cross_project_flow_rejected(self, mutation_db):
        """Flow belonging to different project should be rejected."""
        # Add a externalwebapp flow
        conn = connect_test_db(mutation_db["db_path"])
        stages = json.dumps([{"name": "merged", "executor": "auto"}])
        conn.execute(
            """INSERT INTO deployment_flows (id, project_id, name, stages, created_at)
               VALUES ('externalwebapp-flow', 2, 'ExternalWebappFlow', %s, '2026-04-20T00:00:00Z')""",
            (stages,),
        )
        conn.commit()
        conn.close()

        result = _run_client(
            ["create-item", "--title", "Test", "--type", "issue",
             "--project", "yoke", "--deployment-flow", "externalwebapp-flow"],
            db_path=mutation_db["db_path"],
        )
        assert result.returncode == 1
        data = json.loads(result.stdout.strip())
        assert data["success"] is False
        assert "externalwebapp" in data["error"].lower()

    def test_create_rejects_retired_epic_flag(self, mutation_db):
        """The retired --epic flag should no longer be accepted."""
        result = _run_client(
            ["create-item", "--title", "Child epic", "--type", "epic",
             "--epic", "12"],
            db_path=mutation_db["db_path"],
        )
        assert result.returncode == 2
        assert "Unknown argument: --epic" in result.stderr
