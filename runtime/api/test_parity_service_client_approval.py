"""Parity tests — approval surfaces (read + write)."""

from __future__ import annotations

import json

import pytest

from yoke_core.domain import approval
from runtime.api.fixtures.file_test_db import connect_test_db

# ``_run_service_client`` is the (backend-agnostic) subprocess helper; it copies
# os.environ at call time, so it inherits the per-test ``YOKE_PG_DSN`` repointed
# by the parity-env builders below.
from runtime.api.test_parity import _run_service_client
from runtime.api.parity_service_client_test_helpers import (
    make_read_parity_env,
    make_write_parity_env,
)


@pytest.fixture()
def parity_env():
    # Backend-aware read-parity env using one per-test Postgres database, so the
    # service_client subprocess reads the same database this fixture seeds.
    with make_read_parity_env() as env:
        yield env


@pytest.fixture()
def write_parity_env():
    with make_write_parity_env() as env:
        yield env


# ===========================================================================
# Group 3: Approval and deployment-run transitions
# ===========================================================================


class TestApprovalParity:
    """Verify API approve endpoint and CLI approve-check agree."""

    def test_approve_check_cli_matches_domain_resolution(self, parity_env):
        """CLI approve-check should agree with domain layer on valid approvals."""
        db_path = parity_env["db_path"]

        # CLI: approve-check parity-flow approve-deploy
        result = _run_service_client(
            db_path, "approve-check", "parity-flow", "approve-deploy",
        )
        assert result.returncode == 0
        cli_data = json.loads(result.stdout)
        assert cli_data["approved"] is True
        assert cli_data["next_stage"] == "prod-deploy"

        # Domain layer direct check
        conn = connect_test_db(db_path)
        row = conn.execute(
            "SELECT stages FROM deployment_flows WHERE id = %s",
            ("parity-flow",),
        ).fetchone()
        conn.close()

        stages = approval.parse_flow_stages(row["stages"])
        resolution = approval.resolve_approval(stages, "approve-deploy")
        assert resolution.approved is True
        assert resolution.next_stage == "prod-deploy"

    def test_approve_check_non_approval_stage_rejected(self, parity_env):
        """Both surfaces should reject approving a non-human-approval stage."""
        db_path = parity_env["db_path"]

        # CLI: approve-check parity-flow merged (auto stage, not human-approval)
        result = _run_service_client(
            db_path, "approve-check", "parity-flow", "merged",
        )
        assert result.returncode == 1, "CLI should reject non-approval stage"

        # Domain layer
        conn = connect_test_db(db_path)
        row = conn.execute(
            "SELECT stages FROM deployment_flows WHERE id = %s",
            ("parity-flow",),
        ).fetchone()
        conn.close()

        stages = approval.parse_flow_stages(row["stages"])
        resolution = approval.resolve_approval(stages, "merged")
        assert resolution.approved is False

    def test_approve_check_unknown_flow_rejected(self, parity_env):
        """Both surfaces should reject approving an unknown flow."""
        db_path = parity_env["db_path"]

        result = _run_service_client(
            db_path, "approve-check", "no-such-flow", "approve-deploy",
        )
        assert result.returncode == 1, "CLI should reject unknown flow"

    def test_api_approve_advances_run_stage(self, parity_env):
        """API approve endpoint should advance the run's current_stage."""
        client = parity_env["client"]
        db_path = parity_env["db_path"]

        # Approve item 4 (at approve-deploy stage)
        resp = client.post(
            "/v1/items/4/approve",
            json={"comment": "Parity test approval"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == 4
        assert "approved_at" in data

        # Verify the run's current_stage was advanced in the DB
        conn = connect_test_db(db_path)
        run = conn.execute(
            "SELECT current_stage FROM deployment_runs WHERE id = %s",
            ("run-parity-001",),
        ).fetchone()
        assert run["current_stage"] == "prod-deploy"

        # Verify the item's deploy_stage was also advanced
        item = conn.execute(
            "SELECT deploy_stage, status FROM items WHERE id = %s", (4,)
        ).fetchone()
        assert item["deploy_stage"] == "prod-deploy"
        assert item["status"] == "release"
        conn.close()


class TestApprovalWriteParity:
    """Verify that API POST /v1/items/{id}/approve and service-client
    apply-approval produce matching results for the approval surface."""

    def test_approval_success_both(self, write_parity_env):
        """Both surfaces should advance the deploy stage on a valid approval.

        Uses item 4 which has deploy_stage=approve-deploy with the
        parity-flow containing a human-approval executor at that stage.

        The API returns an ApproveResponse (id, approved_at, comment) and
        applies the stage advancement to the DB.  The CLI returns a mutation
        result with next_stage, run_id, and member_item_ids for the shell
        adapter to apply.
        """
        client = write_parity_env["client"]
        db_path = write_parity_env["db_path"]

        # API approval on item 4
        api_resp = client.post("/v1/items/4/approve", json={})
        assert api_resp.status_code == 200
        api_data = api_resp.json()
        # API returns approved_at confirming the approval happened
        assert "approved_at" in api_data
        assert api_data["id"] == 4

        # Verify the API actually updated the DB
        conn = connect_test_db(db_path)
        row = conn.execute("SELECT deploy_stage FROM items WHERE id = 4").fetchone()
        assert row["deploy_stage"] == "prod-deploy"

        # Now set up another item at the same stage for CLI test
        conn.execute(
            """INSERT INTO items
               (id, title, type, status, priority, project_id, project_sequence,
                deploy_stage, deployment_flow,
                created_at, updated_at, source, frozen)
               VALUES (100, 'CLI approval test', 'issue', 'release', 'high', 1, 100,
                       'approve-deploy', 'parity-flow',
                       '2026-01-01', '2026-01-01', 'user', 0)""",
        )
        conn.execute(
            """INSERT INTO deployment_runs
               (id, project_id, flow, status, current_stage, created_at)
               VALUES ('run-parity-cli', 1, 'parity-flow', 'executing',
                       'approve-deploy', '2026-01-01')""",
        )
        conn.execute(
            """INSERT INTO deployment_run_items (run_id, item_id, added_at)
               VALUES ('run-parity-cli', 100, '2026-01-01')""",
        )
        conn.commit()
        conn.close()

        # CLI approval on item 100
        cli_result = _run_service_client(db_path, "apply-approval", "100")
        assert cli_result.returncode == 0
        cli_data = json.loads(cli_result.stdout)
        assert cli_data["success"] is True
        assert cli_data["next_stage"] == "prod-deploy"

    def test_approval_no_deploy_stage_rejected_both(self, write_parity_env):
        """Both surfaces should reject approval for items without deploy_stage."""
        client = write_parity_env["client"]
        db_path = write_parity_env["db_path"]

        # Item 1 has no deploy_stage
        api_resp = client.post("/v1/items/1/approve", json={})
        assert api_resp.status_code == 409

        cli_result = _run_service_client(db_path, "apply-approval", "1")
        assert cli_result.returncode == 1
        cli_data = json.loads(cli_result.stdout)
        assert cli_data["success"] is False

    def test_approval_nonexistent_item_rejected_both(self, write_parity_env):
        """Both surfaces should reject approval for non-existent items."""
        client = write_parity_env["client"]
        db_path = write_parity_env["db_path"]

        api_resp = client.post("/v1/items/9999/approve", json={})
        assert api_resp.status_code == 404

        cli_result = _run_service_client(db_path, "apply-approval", "9999")
        assert cli_result.returncode == 1
