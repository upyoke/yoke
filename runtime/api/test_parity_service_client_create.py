"""Parity tests — write-side create surface (POST /v1/items vs CLI create-item)."""

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
# Group 7: Write-side parity — create
# ===========================================================================


class TestCreateParity:
    """Verify that API POST /v1/items and service-client create-item produce
    identical validation results and item state for the supported create
    surface."""

    def test_create_success_api_and_cli_agree(self, write_parity_env):
        """Both surfaces should create an item with the same defaults and
        field values.

        API returns the created item directly; CLI returns mutation result
        with field_writes and defaults.  Both must agree on the field values
        that matter: status, priority, type, and flow defaults.
        """
        client = write_parity_env["client"]
        db_path = write_parity_env["db_path"]

        # API create
        api_resp = client.post("/v1/items", json={
            "title": "Parity create test",
            "type": "issue",
            "priority": "high",
        })
        assert api_resp.status_code == 201
        api_item = api_resp.json()

        # CLI create (returns mutation result, not the item itself)
        cli_result = _run_service_client(
            db_path, "create-item",
            "--title", "Parity create CLI",
            "--type", "issue",
            "--priority", "high",
        )
        assert cli_result.returncode == 0
        cli_data = json.loads(cli_result.stdout)
        assert cli_data["success"] is True

        # Both should produce items with the same default fields
        assert api_item["status"] == "idea"
        assert cli_data["field_writes"]["status"] == "idea"
        assert api_item["priority"] == "high"
        assert cli_data["field_writes"]["priority"] == "high"
        # Default flow should be accelerated
        assert cli_data["field_writes"]["flow"] == "accelerated"
        assert cli_data["defaults"]["flow"] == "accelerated"

    def test_create_invalid_title_rejected_both(self, write_parity_env):
        """Both surfaces should reject a title exceeding 100 characters."""
        client = write_parity_env["client"]
        db_path = write_parity_env["db_path"]
        long_title = "X" * 101

        # API
        api_resp = client.post("/v1/items", json={
            "title": long_title,
            "type": "issue",
        })
        assert api_resp.status_code == 422

        # CLI
        cli_result = _run_service_client(
            db_path, "create-item",
            "--title", long_title,
            "--type", "issue",
        )
        assert cli_result.returncode == 1
        cli_data = json.loads(cli_result.stdout)
        assert cli_data["success"] is False
        assert "100" in cli_data["error"]

    def test_create_invalid_type_rejected_both(self, write_parity_env):
        """Both surfaces should reject an invalid item type."""
        client = write_parity_env["client"]
        db_path = write_parity_env["db_path"]

        # API
        api_resp = client.post("/v1/items", json={
            "title": "Bad type",
            "type": "task",
        })
        assert api_resp.status_code == 422

        # CLI
        cli_result = _run_service_client(
            db_path, "create-item",
            "--title", "Bad type",
            "--type", "task",
        )
        assert cli_result.returncode == 1
        cli_data = json.loads(cli_result.stdout)
        assert cli_data["success"] is False

    def test_create_invalid_priority_rejected_both(self, write_parity_env):
        """Both surfaces should reject an invalid priority."""
        client = write_parity_env["client"]
        db_path = write_parity_env["db_path"]

        # API
        api_resp = client.post("/v1/items", json={
            "title": "Bad priority",
            "type": "issue",
            "priority": "critical",
        })
        assert api_resp.status_code == 422

        # CLI
        cli_result = _run_service_client(
            db_path, "create-item",
            "--title", "Bad priority",
            "--type", "issue",
            "--priority", "critical",
        )
        assert cli_result.returncode == 1
        cli_data = json.loads(cli_result.stdout)
        assert cli_data["success"] is False

    def test_create_flow_project_mismatch_rejected_both(self, write_parity_env):
        """Both surfaces should reject a flow that belongs to a different
        project than the item."""
        client = write_parity_env["client"]
        db_path = write_parity_env["db_path"]

        # API — parity-flow belongs to 'yoke', item says 'buzz'
        api_resp = client.post("/v1/items", json={
            "title": "Cross project flow",
            "type": "issue",
            "project": "buzz",
            "deployment_flow": "parity-flow",
        })
        assert api_resp.status_code == 422

        # CLI
        cli_result = _run_service_client(
            db_path, "create-item",
            "--title", "Cross project flow",
            "--type", "issue",
            "--project", "buzz",
            "--deployment-flow", "parity-flow",
        )
        assert cli_result.returncode == 1
        cli_data = json.loads(cli_result.stdout)
        assert cli_data["success"] is False

    def test_create_retired_epic_field_rejected_both(self, write_parity_env):
        """Both create surfaces reject the retired epic-parent surface."""
        client = write_parity_env["client"]
        db_path = write_parity_env["db_path"]

        api_resp = client.post("/v1/items", json={
            "title": "Retired parent ref",
            "type": "issue",
            "epic": 11,
        })
        assert api_resp.status_code == 422

        cli_result = _run_service_client(
            db_path, "create-item", "--title", "Retired parent ref",
            "--type", "issue", "--epic", "11",
        )
        assert cli_result.returncode == 2
