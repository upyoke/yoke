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
)
from runtime.api.deployment_stage_approval_fixture import (
    yield_seeded_api_db_with_default_approvals,
)
from runtime.api.fixtures.file_test_db import connect_test_db


@pytest.fixture()
def test_db():
    yield from yield_seeded_api_db_with_default_approvals()


@pytest.fixture()
def client(test_db):
    yield from make_client_fixture()


class TestApproveItem:
    def test_approve_routes_to_inbox_without_moving_run_state(
        self,
        client,
        test_db,
    ):
        with patch("yoke_core.domain.events.emit_event") as mock_emit:
            resp = client.post(
                "/v1/items/4/approve",
                json={
                    "comment": "Looks good",
                },
            )
        assert resp.status_code == 409
        data = resp.json()
        assert data["error"]["code"] == "APPROVAL_REQUIRED"
        assert "Inbox decision request" in data["error"]["message"]

        conn = connect_test_db(test_db["db_path"])
        item_row = conn.execute(
            "SELECT status, deploy_stage FROM items WHERE id = 4"
        ).fetchone()
        assert item_row["status"] == "release"
        assert item_row["deploy_stage"] == "approve-deploy"
        run_row = conn.execute(
            "SELECT current_stage FROM deployment_runs WHERE id = 'run-20260325-001'"
        ).fetchone()
        assert run_row["current_stage"] == "approve-deploy"
        decision = conn.execute(
            "SELECT status FROM decision_requests "
            "WHERE subject_key='run-20260325-001:approve-deploy'"
        ).fetchone()
        conn.close()
        assert decision["status"] == "pending"
        mock_emit.assert_not_called()

    def test_approve_no_comment(self, client):
        resp = client.post("/v1/items/4/approve", json={})
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "APPROVAL_REQUIRED"

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
        assert data["error"]["code"] == "NO_ACTIVE_RUN"

    def test_approve_non_approval_stage(self, client, test_db):
        """Item at a non-human-approval stage should be rejected."""
        # Set the run to a non-approval stage.
        conn = connect_test_db(test_db["db_path"])
        conn.execute(
            "UPDATE deployment_runs SET current_stage = 'prod-deploy' "
            "WHERE id = 'run-20260325-001'"
        )
        conn.commit()
        conn.close()

        resp = client.post("/v1/items/4/approve", json={})
        assert resp.status_code == 409
        data = resp.json()
        assert data["error"]["code"] == "INVALID_STATE"
        assert "not a human-approval stage" in data["error"]["message"]

    def test_pending_approval_does_not_emit_granted_event(self, client):
        with patch(
            "yoke_core.domain.events.emit_event",
            side_effect=RuntimeError("emitter boom"),
        ) as emit:
            resp = client.post(
                "/v1/items/4/approve",
                json={
                    "comment": "LGTM",
                },
            )
        assert resp.status_code == 409
        emit.assert_not_called()

    def test_approve_comment_too_long(self, client):
        resp = client.post(
            "/v1/items/4/approve",
            json={
                "comment": "x" * 501,
            },
        )
        assert resp.status_code == 422
        data = resp.json()
        assert data["error"]["code"] == "VALIDATION_ERROR"
        assert "comment" in data["error"]["message"].lower()

    def test_approve_no_deployment_flow(self, client, test_db):
        """Item with deploy_stage but no deployment_flow should be rejected."""
        conn = connect_test_db(test_db["db_path"])
        conn.execute(
            """INSERT INTO items
               (id, title, workflow_id, workflow_version_id, status, priority, project_id, project_sequence,
                created_at, updated_at, source, deploy_stage, deployment_flow)
               VALUES (6, 'No flow', 'issue', (SELECT current_version_id FROM workflows WHERE id='issue'), 'release', 'medium', 1, 6,
                       '2026-03-01T00:00:00Z', '2026-03-01T00:00:00Z', 'user',
                       'some-stage', NULL)"""
        )
        conn.commit()
        conn.close()

        resp = client.post("/v1/items/6/approve", json={})
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "NO_ACTIVE_RUN"

    def test_approve_without_run_refuses_item_only_fallback(self, client, test_db):
        # Create an item with approval stage but no run
        conn = connect_test_db(test_db["db_path"])
        conn.execute(
            """INSERT INTO items
               (id, title, workflow_id, workflow_version_id, status, priority, project_id, project_sequence,
                created_at, updated_at, source, deploy_stage, deployment_flow)
               VALUES (7, 'No run item', 'issue', (SELECT current_version_id FROM workflows WHERE id='issue'), 'release', 'medium', 1, 7,
                       '2026-03-01T00:00:00Z', '2026-03-01T00:00:00Z', 'user',
                       'approve-deploy', 'test-approval-flow')"""
        )
        conn.commit()
        conn.close()

        resp = client.post("/v1/items/7/approve", json={})
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "NO_ACTIVE_RUN"

        conn = connect_test_db(test_db["db_path"])
        row = conn.execute(
            "SELECT status, deploy_stage FROM items WHERE id = 7"
        ).fetchone()
        assert row["status"] == "release"
        assert row["deploy_stage"] == "approve-deploy"
        conn.close()

    def test_pending_run_approval_moves_no_members(self, client, test_db):
        conn = connect_test_db(test_db["db_path"])
        # Add a second item to the same run
        conn.execute(
            """INSERT INTO items
               (id, title, workflow_id, workflow_version_id, status, priority, project_id, project_sequence,
                created_at, updated_at, source, deploy_stage, deployment_flow)
               VALUES (8, 'Second run member', 'issue', (SELECT current_version_id FROM workflows WHERE id='issue'), 'release', 'medium', 1, 8,
                       '2026-03-01T00:00:00Z', '2026-03-01T00:00:00Z', 'user',
                       'approve-deploy', 'test-approval-flow')"""
        )
        conn.execute(
            """INSERT INTO deployment_run_items (run_id, item_id, added_at)
               VALUES ('run-20260325-001', 8, '2026-03-25T00:00:00Z')"""
        )
        conn.commit()
        conn.close()

        resp = client.post("/v1/items/4/approve", json={})
        assert resp.status_code == 409

        # Both members should be advanced
        conn = connect_test_db(test_db["db_path"])
        p = _p(conn)
        for item_id in [4, 8]:
            row = conn.execute(
                f"SELECT deploy_stage FROM items WHERE id = {p}", (item_id,)
            ).fetchone()
            assert row["deploy_stage"] == "approve-deploy"
        conn.close()
