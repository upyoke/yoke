"""PATCH /v1/items/{id} update-endpoint tests (TestUpdateItem).

Function-call coverage of ``items.scalar.update`` lives in the sibling
``test_api_items_update_functions.py``. Both files share the same
mutation gate path (``mutations.prepare_update`` →
``backlog.execute_update``); the split keeps each test file under the
350-line authored-file budget.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from runtime.api.api_items_test_helpers import (
    _client_for_db,
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


class TestUpdateItem:
    def test_update_title(self, client, test_db):
        """PATCH /v1/items/{id} updates title via shared mutation layer."""
        resp = client.patch("/v1/items/1", json={"title": "Updated title"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "Updated title"

    def test_update_priority(self, client, test_db):
        resp = client.patch("/v1/items/1", json={"priority": "low"})
        assert resp.status_code == 200
        assert resp.json()["priority"] == "low"

    def test_update_status(self, client, test_db):
        conn = connect_test_db(test_db["db_path"])
        conn.execute(
            """INSERT INTO items
               (id, title, type, status, priority, project_id, project_sequence,
                created_at, updated_at, source, deploy_stage)
               VALUES (6, 'In-flight epic', 'epic', 'planned', 'medium', 1, 6,
                       '2026-03-01T00:00:00Z', '2026-03-02T00:00:00Z', 'user', NULL)"""
        )
        conn.commit()
        conn.close()

        resp = client.patch("/v1/items/6", json={"status": "reviewed-implementation"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "reviewed-implementation"

    def test_update_frozen(self, client, test_db):
        resp = client.patch("/v1/items/1", json={"frozen": True})
        assert resp.status_code == 200
        assert resp.json()["frozen"] is True

    def test_update_project(self, client, test_db):
        resp = client.patch("/v1/items/1", json={"project": "buzz"})
        assert resp.status_code == 200
        assert resp.json()["project"] == "buzz"

    def test_update_item_not_found(self, client, test_db):
        resp = client.patch("/v1/items/999", json={"title": "Not found"})
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "NOT_FOUND"

    def test_update_no_fields(self, client, test_db):
        """Empty update body returns validation error."""
        resp = client.patch("/v1/items/1", json={})
        assert resp.status_code == 422

    def test_update_invalid_priority(self, client, test_db):
        resp = client.patch("/v1/items/1", json={"priority": "critical"})
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "VALIDATION_ERROR"

    def test_update_title_too_long(self, client, test_db):
        resp = client.patch("/v1/items/1", json={"title": "x" * 101})
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "VALIDATION_ERROR"

    def test_update_invalid_status(self, client, test_db):
        resp = client.patch("/v1/items/1", json={"status": "bogus"})
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "VALIDATION_ERROR"

    def test_update_multiple_fields(self, client, test_db):
        """Multiple fields in a single PATCH request."""
        resp = client.patch("/v1/items/1", json={
            "priority": "low",
            "title": "Updated title",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["priority"] == "low"
        assert data["title"] == "Updated title"

    def test_update_uses_mutation_layer(self, client, test_db):
        """AC: PATCH flows through shared mutation layer, not raw SQL."""
        conn = connect_test_db(test_db["db_path"])
        conn.execute(
            """INSERT INTO items
               (id, title, type, status, priority, project_id, project_sequence, rework_count,
                created_at, updated_at, source, deploy_stage)
               VALUES (7, 'Reopened issue', 'issue', 'done', 'medium', 1, 7, 0,
                       '2026-03-01T00:00:00Z', '2026-03-02T00:00:00Z', 'user', NULL)"""
        )
        conn.commit()
        conn.close()

        # Rework detection: transitioning from done -> implementing increments rework_count
        resp = client.patch("/v1/items/7", json={"status": "implementing"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "implementing"
        assert data["rework_count"] == 1  # incremented by mutation layer

    def test_update_rejects_unregistered_deployment_flow(self, client, test_db):
        """PATCH rejects an unregistered non-empty deployment_flow value."""
        resp = client.patch("/v1/items/1", json={"deployment_flow": "garbage"})
        assert resp.status_code == 422
        data = resp.json()
        assert data["error"]["code"] == "VALIDATION_ERROR"
        assert "garbage" in data["error"]["message"]
        assert "is not registered" in data["error"]["message"]

    def test_update_rejects_literal_none_deployment_flow(self, client, test_db):
        """PATCH rejects the literal string 'none' on the update path."""
        resp = client.patch("/v1/items/1", json={"deployment_flow": "none"})
        assert resp.status_code == 422
        data = resp.json()
        assert data["error"]["code"] == "VALIDATION_ERROR"
        assert "'none'" in data["error"]["message"]

    def test_update_accepts_registered_deployment_flow(self, client, test_db):
        """PATCH accepts a registered deployment_flow value."""
        resp = client.patch(
            "/v1/items/1", json={"deployment_flow": "test-approval-flow"}
        )
        assert resp.status_code == 200
        assert resp.json()["deployment_flow"] == "test-approval-flow"

    def test_update_accepts_null_sentinel_deployment_flow(self, client, test_db):
        """PATCH treats string null deployment_flow as unset."""
        resp = client.patch("/v1/items/1", json={"deployment_flow": "null"})
        assert resp.status_code == 200
        assert resp.json()["deployment_flow"] is None

    def test_update_deployed_to_handles_missing_project_capabilities_table(self, test_db):
        conn = connect_test_db(test_db["db_path"])
        conn.execute("DROP TABLE project_capabilities")
        conn.commit()
        conn.close()

        with _client_for_db(test_db["db_path"]) as client:
            resp = client.patch("/v1/items/1", json={"deployed_to": "local"})

        assert resp.status_code == 422
        data = resp.json()
        assert data["error"]["code"] == "VALIDATION_ERROR"
        assert "No deployment environments" in data["error"]["message"]
