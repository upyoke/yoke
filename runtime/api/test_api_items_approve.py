"""POST /v1/items/{id}/approve human-approval tests (TestApproveItem)."""

from __future__ import annotations

import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from runtime.api.api_items_test_helpers import (
    _p,
    make_client_fixture,
    make_test_db_fixture,
)
from runtime.api.fixtures.file_test_db import connect_test_db


@pytest.fixture()
def test_db():
    yield from make_test_db_fixture()


@pytest.fixture()
def client(test_db):
    yield from make_client_fixture()


class TestApproveItem:
    def test_approve_advances_run_and_item_state(self, client, test_db):
        """AC: Approval goes through shared mutation layer, advances run+item state.

        emit-event.sh was deleted in wave 3 lane C. The approval
        event now fires through yoke_core.domain.events.emit_event
        directly — we patch that instead of subprocess.run.
        """
        with patch("yoke_core.domain.events.emit_event") as mock_emit:
            mock_emit.return_value = {"event_name": "DeploymentApprovalGranted"}
            resp = client.post("/v1/items/4/approve", json={
                "comment": "Looks good",
            })
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == 4
        assert data["comment"] == "Looks good"
        assert "approved_at" in data

        # Item state: deploy_stage advanced to next stage, status remains release
        conn = connect_test_db(test_db["db_path"])
        item_row = conn.execute(
            "SELECT status, deploy_stage FROM items WHERE id = 4"
        ).fetchone()
        assert item_row["status"] == "release"
        assert item_row["deploy_stage"] == "prod-deploy"

        # Run's current_stage advanced atomically
        run_row = conn.execute(
            "SELECT current_stage FROM deployment_runs WHERE id = 'run-20260325-001'"
        ).fetchone()
        assert run_row["current_stage"] == "prod-deploy"

        conn.close()

        # Verify the native emitter was called for approval telemetry
        mock_emit.assert_called_once()
        args, kwargs = mock_emit.call_args
        assert args[0] == "DeploymentApprovalGranted"
        assert kwargs["event_kind"] == "lifecycle"
        assert kwargs["event_type"] == "deployment_run"
        assert kwargs["item_id"] == "4"

    def test_approve_no_comment(self, client):
        with patch("yoke_core.api.main.subprocess.run"):
            resp = client.post("/v1/items/4/approve", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert data["comment"] is None

    def test_approve_item_not_found(self, client):
        resp = client.post("/v1/items/999/approve", json={})
        assert resp.status_code == 404
        data = resp.json()
        assert data["error"]["code"] == "NOT_FOUND"
        assert "999" in data["error"]["message"]

    def test_approve_no_deploy_stage(self, client):
        """Item 1 has no deploy_stage (NULL) — cannot approve."""
        resp = client.post("/v1/items/1/approve", json={})
        assert resp.status_code == 409
        data = resp.json()
        assert data["error"]["code"] == "INVALID_STATE"

    def test_approve_non_approval_stage(self, client, test_db):
        """Item at a non-human-approval stage should be rejected."""
        # Set item 4 to a non-approval stage
        conn = connect_test_db(test_db["db_path"])
        conn.execute("UPDATE items SET deploy_stage = 'prod-deploy' WHERE id = 4")
        conn.commit()
        conn.close()

        resp = client.post("/v1/items/4/approve", json={})
        assert resp.status_code == 409
        data = resp.json()
        assert data["error"]["code"] == "INVALID_STATE"
        assert "not a human-approval stage" in data["error"]["message"]

    def test_approve_emit_event_failure_nonfatal(self, client, test_db):
        """Approval succeeds even if the native emitter fails.

        the approval event was migrated off emit-event.sh to
        yoke_core.domain.events.emit_event. The failure-nonfatal
        contract is preserved — we simulate an emitter exception and
        confirm the approval still completes.
        """
        with patch(
            "yoke_core.domain.events.emit_event",
            side_effect=RuntimeError("emitter boom"),
        ):
            resp = client.post("/v1/items/4/approve", json={
                "comment": "LGTM",
            })
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == 4

        # Item and run state should still be advanced
        conn = connect_test_db(test_db["db_path"])
        item_row = conn.execute(
            "SELECT status, deploy_stage FROM items WHERE id = 4"
        ).fetchone()
        assert item_row["status"] == "release"
        assert item_row["deploy_stage"] == "prod-deploy"

        run_row = conn.execute(
            "SELECT current_stage FROM deployment_runs WHERE id = 'run-20260325-001'"
        ).fetchone()
        assert run_row["current_stage"] == "prod-deploy"
        conn.close()

    def test_approve_comment_too_long(self, client):
        resp = client.post("/v1/items/4/approve", json={
            "comment": "x" * 501,
        })
        assert resp.status_code == 422
        data = resp.json()
        assert data["error"]["code"] == "VALIDATION_ERROR"
        assert "comment" in data["error"]["message"].lower()

    def test_approve_no_deployment_flow(self, client, test_db):
        """Item with deploy_stage but no deployment_flow should be rejected."""
        conn = connect_test_db(test_db["db_path"])
        conn.execute(
            """INSERT INTO items
               (id, title, type, status, priority, project_id, project_sequence,
                created_at, updated_at, source, deploy_stage, deployment_flow)
               VALUES (6, 'No flow', 'issue', 'release', 'medium', 1, 6,
                       '2026-03-01T00:00:00Z', '2026-03-01T00:00:00Z', 'user',
                       'some-stage', NULL)"""
        )
        conn.commit()
        conn.close()

        resp = client.post("/v1/items/6/approve", json={})
        assert resp.status_code == 409
        assert "no deployment_flow" in resp.json()["error"]["message"]

    def test_approve_without_run_falls_back_to_item_only(self, client, test_db):
        """AC-4: When no active run exists, item deploy_stage is still advanced."""
        # Create an item with approval stage but no run
        conn = connect_test_db(test_db["db_path"])
        conn.execute(
            """INSERT INTO items
               (id, title, type, status, priority, project_id, project_sequence,
                created_at, updated_at, source, deploy_stage, deployment_flow)
               VALUES (7, 'No run item', 'issue', 'release', 'medium', 1, 7,
                       '2026-03-01T00:00:00Z', '2026-03-01T00:00:00Z', 'user',
                       'approve-deploy', 'test-approval-flow')"""
        )
        conn.commit()
        conn.close()

        with patch("yoke_core.api.main.subprocess.run"):
            resp = client.post("/v1/items/7/approve", json={})
        assert resp.status_code == 200

        conn = connect_test_db(test_db["db_path"])
        row = conn.execute(
            "SELECT status, deploy_stage FROM items WHERE id = 7"
        ).fetchone()
        assert row["status"] == "release"
        assert row["deploy_stage"] == "prod-deploy"
        conn.close()

    def test_approve_multi_item_run_advances_all_members(self, client, test_db):
        """AC-1: All member items in the run get their deploy_stage advanced."""
        conn = connect_test_db(test_db["db_path"])
        # Add a second item to the same run
        conn.execute(
            """INSERT INTO items
               (id, title, type, status, priority, project_id, project_sequence,
                created_at, updated_at, source, deploy_stage, deployment_flow)
               VALUES (8, 'Second run member', 'issue', 'release', 'medium', 1, 8,
                       '2026-03-01T00:00:00Z', '2026-03-01T00:00:00Z', 'user',
                       'approve-deploy', 'test-approval-flow')"""
        )
        conn.execute(
            """INSERT INTO deployment_run_items (run_id, item_id, added_at)
               VALUES ('run-20260325-001', 8, '2026-03-25T00:00:00Z')"""
        )
        conn.commit()
        conn.close()

        with patch("yoke_core.api.main.subprocess.run"):
            resp = client.post("/v1/items/4/approve", json={})
        assert resp.status_code == 200

        # Both members should be advanced
        conn = connect_test_db(test_db["db_path"])
        p = _p(conn)
        for item_id in [4, 8]:
            row = conn.execute(
                f"SELECT deploy_stage FROM items WHERE id = {p}", (item_id,)
            ).fetchone()
            assert row["deploy_stage"] == "prod-deploy", f"Item {item_id} not advanced"
        conn.close()
