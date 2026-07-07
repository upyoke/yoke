"""Parity tests — unsupported field regression (mutation surface stays narrow)."""

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
# Group 8: Unsupported field regression
# ===========================================================================


class TestUnsupportedFieldRegression:
    """Verify that fields outside the supported mutation surface remain
    on the explicit shell fallback path and are rejected by the shared
    mutation layer.

    This ensures the mutation surface stays intentionally narrow and does
    not accidentally absorb fields that should remain shell-owned.
    """

    def test_api_rejects_body_field(self, write_parity_env):
        """The API PATCH endpoint should not accept 'body' updates."""
        client = write_parity_env["client"]
        # body is not in the Pydantic model, so FastAPI should 422
        api_resp = client.patch("/v1/items/1", json={"body": "new body"})
        # FastAPI rejects unknown fields or ignores them depending on model config
        # If ignored (no valid field provided), returns 422 for empty update
        assert api_resp.status_code == 422

    def test_cli_rejects_body_field(self, write_parity_env):
        """The service-client update-item should reject 'body' updates."""
        db_path = write_parity_env["db_path"]
        cli_result = _run_service_client(
            db_path, "update-item", "1",
            "--field", "body", "--value", "new body",
        )
        assert cli_result.returncode == 1
        cli_data = json.loads(cli_result.stdout)
        assert cli_data["success"] is False
        assert "UNSUPPORTED_FIELD" in cli_data.get("error_code", "")

    def test_api_rejects_source_field(self, write_parity_env):
        """The API PATCH endpoint should not accept 'source' updates."""
        client = write_parity_env["client"]
        api_resp = client.patch("/v1/items/1", json={"source": "auto"})
        assert api_resp.status_code == 422

    def test_cli_rejects_source_field(self, write_parity_env):
        """The service-client update-item should reject 'source' updates."""
        db_path = write_parity_env["db_path"]
        cli_result = _run_service_client(
            db_path, "update-item", "1",
            "--field", "source", "--value", "auto",
        )
        assert cli_result.returncode == 1
        cli_data = json.loads(cli_result.stdout)
        assert cli_data["success"] is False

    def test_cli_rejects_epic_field(self, write_parity_env):
        """The service-client update-item should reject 'epic' updates."""
        db_path = write_parity_env["db_path"]
        cli_result = _run_service_client(
            db_path, "update-item", "1",
            "--field", "epic", "--value", "42",
        )
        assert cli_result.returncode == 1
        cli_data = json.loads(cli_result.stdout)
        assert cli_data["success"] is False
        assert "UNSUPPORTED_FIELD" in cli_data.get("error_code", "")

    def test_cli_rejects_type_field(self, write_parity_env):
        """The service-client update-item should reject 'type' updates."""
        db_path = write_parity_env["db_path"]
        cli_result = _run_service_client(
            db_path, "update-item", "1",
            "--field", "type", "--value", "epic",
        )
        assert cli_result.returncode == 1
        cli_data = json.loads(cli_result.stdout)
        assert cli_data["success"] is False
        assert "UNSUPPORTED_FIELD" in cli_data.get("error_code", "")

    def test_domain_layer_rejects_unsupported_fields(self):
        """The domain mutation layer should reject all fields outside the
        supported update surface."""
        from yoke_core.domain.mutations import (
            SUPPORTED_UPDATE_FIELDS, prepare_update, ItemState,
        )

        item = ItemState(
            id=1, title="Test", item_type="issue",
            status="implementing", priority="medium",
        )

        # worktree is a supported update field (advance worktree-phase writes it);
        # the documented update surface sits alongside the structured content
        # fields like spec/technical_plan which use their own write path.
        unsupported_fields = ["body", "source", "epic", "type", "github_issue",
                              "created_at", "updated_at", "flow",
                              "merged_at", "rework_count"]

        for field_name in unsupported_fields:
            result = prepare_update(item=item, field_name=field_name, value="test")
            assert not result.success, f"Expected {field_name} to be rejected"
            assert result.error_code == "UNSUPPORTED_FIELD", (
                f"Expected UNSUPPORTED_FIELD for {field_name}, got {result.error_code}"
            )

    def test_supported_update_fields_are_narrow(self):
        """The supported update surface should contain exactly the documented
        set and nothing more."""
        from yoke_core.domain.mutations import SUPPORTED_UPDATE_FIELDS

        expected = {
            "status", "frozen", "blocked", "blocked_reason",
            "priority", "project", "deployment_flow", "deployed_to", "title",
            "worktree",
        }
        assert SUPPORTED_UPDATE_FIELDS == expected, (
            f"SUPPORTED_UPDATE_FIELDS has drifted: "
            f"extra={SUPPORTED_UPDATE_FIELDS - expected}, "
            f"missing={expected - SUPPORTED_UPDATE_FIELDS}"
        )
