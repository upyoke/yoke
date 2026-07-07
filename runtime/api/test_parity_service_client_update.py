"""Parity tests — write-side update surface (PATCH /v1/items/{id} vs CLI update-item)."""

from __future__ import annotations

import json

import pytest

from runtime.api.test_parity import _run_service_client
from runtime.api.parity_service_client_test_helpers import make_write_parity_env


@pytest.fixture()
def write_parity_env():
    with make_write_parity_env() as env:
        yield env


# ===========================================================================
# Group 7: Write-side parity — update
# ===========================================================================


class TestUpdateParity:
    """Verify that API PATCH /v1/items/{id} and service-client update-item
    produce identical validation results for the supported update surface."""

    def test_update_status_accepted_both(self, write_parity_env):
        """Both surfaces should accept a valid status transition."""
        client = write_parity_env["client"]
        db_path = write_parity_env["db_path"]

        # Item 1 is at status=implementing (task), transition to blocked
        api_resp = client.patch("/v1/items/1", json={"status": "blocked"})
        assert api_resp.status_code == 200
        assert api_resp.json()["status"] == "blocked"

        # Now update via CLI (item 3 is issue at idea, move to refining-idea
        # — a valid issue-workflow-type transition).
        cli_result = _run_service_client(
            db_path, "update-item", "3",
            "--field", "status", "--value", "refining-idea",
        )
        assert cli_result.returncode == 0
        cli_data = json.loads(cli_result.stdout)
        assert cli_data["success"] is True

    def test_update_invalid_status_rejected_both(self, write_parity_env):
        """Both surfaces should reject an invalid status value."""
        client = write_parity_env["client"]
        db_path = write_parity_env["db_path"]

        # API
        api_resp = client.patch("/v1/items/1", json={"status": "bogus"})
        assert api_resp.status_code == 422

        # CLI
        cli_result = _run_service_client(
            db_path, "update-item", "1",
            "--field", "status", "--value", "bogus",
        )
        assert cli_result.returncode == 1
        cli_data = json.loads(cli_result.stdout)
        assert cli_data["success"] is False

    def test_update_title_accepted_both(self, write_parity_env):
        """Both surfaces should accept a valid title update."""
        client = write_parity_env["client"]
        db_path = write_parity_env["db_path"]

        api_resp = client.patch("/v1/items/1", json={"title": "New title"})
        assert api_resp.status_code == 200
        assert api_resp.json()["title"] == "New title"

        cli_result = _run_service_client(
            db_path, "update-item", "3",
            "--field", "title", "--value", "CLI title",
        )
        assert cli_result.returncode == 0
        cli_data = json.loads(cli_result.stdout)
        assert cli_data["success"] is True

    def test_update_title_too_long_rejected_both(self, write_parity_env):
        """Both surfaces should reject a title exceeding 100 characters."""
        client = write_parity_env["client"]
        db_path = write_parity_env["db_path"]
        long_title = "X" * 101

        api_resp = client.patch("/v1/items/1", json={"title": long_title})
        assert api_resp.status_code == 422

        cli_result = _run_service_client(
            db_path, "update-item", "1",
            "--field", "title", "--value", long_title,
        )
        assert cli_result.returncode == 1
        cli_data = json.loads(cli_result.stdout)
        assert cli_data["success"] is False
        assert "100" in cli_data["error"]

    def test_update_priority_accepted_both(self, write_parity_env):
        """Both surfaces should accept a valid priority value."""
        client = write_parity_env["client"]
        db_path = write_parity_env["db_path"]

        api_resp = client.patch("/v1/items/1", json={"priority": "low"})
        assert api_resp.status_code == 200

        cli_result = _run_service_client(
            db_path, "update-item", "3",
            "--field", "priority", "--value", "high",
        )
        assert cli_result.returncode == 0

    def test_update_priority_invalid_rejected_both(self, write_parity_env):
        """Both surfaces should reject an invalid priority."""
        client = write_parity_env["client"]
        db_path = write_parity_env["db_path"]

        api_resp = client.patch("/v1/items/1", json={"priority": "urgent"})
        assert api_resp.status_code == 422

        cli_result = _run_service_client(
            db_path, "update-item", "1",
            "--field", "priority", "--value", "urgent",
        )
        assert cli_result.returncode == 1

    def test_update_nonexistent_item_rejected_both(self, write_parity_env):
        """Both surfaces should reject updates to a non-existent item."""
        client = write_parity_env["client"]
        db_path = write_parity_env["db_path"]

        api_resp = client.patch("/v1/items/9999", json={"title": "No item"})
        assert api_resp.status_code == 404

        cli_result = _run_service_client(
            db_path, "update-item", "9999",
            "--field", "title", "--value", "No item",
        )
        assert cli_result.returncode == 1
        cli_data = json.loads(cli_result.stdout)
        assert cli_data["success"] is False

    def test_update_frozen_accepted_both(self, write_parity_env):
        """Both surfaces should accept boolean frozen updates."""
        client = write_parity_env["client"]
        db_path = write_parity_env["db_path"]

        api_resp = client.patch("/v1/items/1", json={"frozen": True})
        assert api_resp.status_code == 200

        cli_result = _run_service_client(
            db_path, "update-item", "3",
            "--field", "frozen", "--value", "true",
        )
        assert cli_result.returncode == 0
