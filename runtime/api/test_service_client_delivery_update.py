"""Tests for service_client update-item mutation command.

Split from ``test_service_client_delivery.py``. The shared
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
# update-item tests task 3
# ---------------------------------------------------------------------------


class TestUpdateItem:
    """Tests for update-item mutation command."""

    def test_update_status_success(self, mutation_db):
        """Update status on existing item returns success JSON."""
        conn = connect_test_db(mutation_db["db_path"])
        conn.execute(
            """INSERT INTO qa_requirements
               (item_id, qa_kind, qa_phase, success_policy)
               VALUES (11, 'implementation_review', 'verification', 'blocking')"""
        )
        conn.commit()
        conn.close()

        result = _run_client(
            ["update-item", "11", "--field", "status", "--value", "reviewing-implementation"],
            db_path=mutation_db["db_path"],
        )
        assert result.returncode == 0
        data = json.loads(result.stdout.strip())
        assert data["success"] is True
        assert data["field_writes"]["status"] == "reviewing-implementation"
        assert "updated_at" in data["field_writes"]
        assert any(e["kind"] == "status_transitioned" for e in data["events"])

    def test_validate_update_alias_marks_preflight_only(self, mutation_db):
        """validate-update makes the no-write contract machine-readable."""
        result = _run_client(
            ["validate-update", "11", "--field", "priority", "--value", "high"],
            db_path=mutation_db["db_path"],
        )

        assert result.returncode == 0
        data = json.loads(result.stdout.strip())
        assert data["success"] is True
        assert data["preflight_only"] is True
        assert data["field_writes"]["priority"] == "high"

    def test_update_item_legacy_alias_also_marks_preflight_only(self, mutation_db):
        """The one-release compatibility alias keeps the same safety signal."""
        result = _run_client(
            ["update-item", "11", "--field", "priority", "--value", "high"],
            db_path=mutation_db["db_path"],
        )

        assert result.returncode == 0
        data = json.loads(result.stdout.strip())
        assert data["success"] is True
        assert data["preflight_only"] is True

    def test_update_priority_success(self, mutation_db):
        """Update priority returns success."""
        result = _run_client(
            ["update-item", "11", "--field", "priority", "--value", "high"],
            db_path=mutation_db["db_path"],
        )
        assert result.returncode == 0
        data = json.loads(result.stdout.strip())
        assert data["success"] is True
        assert data["field_writes"]["priority"] == "high"

    def test_update_title_success(self, mutation_db):
        """Update title returns success."""
        result = _run_client(
            ["update-item", "11", "--field", "title", "--value", "New title"],
            db_path=mutation_db["db_path"],
        )
        assert result.returncode == 0
        data = json.loads(result.stdout.strip())
        assert data["success"] is True
        assert data["field_writes"]["title"] == "New title"

    def test_update_invalid_status_rejected(self, mutation_db):
        """Invalid status string should be rejected."""
        result = _run_client(
            ["update-item", "11", "--field", "status", "--value", "bogus"],
            db_path=mutation_db["db_path"],
        )
        assert result.returncode == 1
        data = json.loads(result.stdout.strip())
        assert data["success"] is False
        assert "not a valid" in data["error"] and "status" in data["error"]

    def test_update_unsupported_field_rejected(self, mutation_db):
        """Field not in the supported surface should be rejected."""
        result = _run_client(
            ["update-item", "11", "--field", "body", "--value", "some text"],
            db_path=mutation_db["db_path"],
        )
        assert result.returncode == 1
        data = json.loads(result.stdout.strip())
        assert data["success"] is False
        assert data["error_code"] == "UNSUPPORTED_FIELD"

    def test_update_nonexistent_item_rejected(self, mutation_db):
        """Updating a nonexistent item should return NOT_FOUND."""
        result = _run_client(
            ["update-item", "9999", "--field", "status", "--value", "active"],
            db_path=mutation_db["db_path"],
        )
        assert result.returncode == 1
        data = json.loads(result.stdout.strip())
        assert data["success"] is False
        assert data["error_code"] == "NOT_FOUND"

    def test_update_done_without_nonce_rejected(self, mutation_db):
        """Transition to done without --done-nonce-verified should be rejected."""
        result = _run_client(
            ["update-item", "11", "--field", "status", "--value", "done"],
            db_path=mutation_db["db_path"],
        )
        assert result.returncode == 1
        data = json.loads(result.stdout.strip())
        assert data["success"] is False
        assert data["error_code"] == "GATE_DONE_NONCE"

    def test_update_done_with_nonce_and_force(self, mutation_db):
        """Transition to done with --force should succeed."""
        result = _run_client(
            ["update-item", "11", "--field", "status", "--value", "done",
             "--force"],
            db_path=mutation_db["db_path"],
        )
        assert result.returncode == 0
        data = json.loads(result.stdout.strip())
        assert data["success"] is True
        assert data["field_writes"]["status"] == "done"
        # Done cleanup should be present
        assert any(e["kind"] == "done_cleanup" for e in data["events"])
