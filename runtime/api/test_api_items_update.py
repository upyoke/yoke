"""PATCH /v1/items/{id} update-endpoint tests (TestUpdateItem).

Function-call coverage of ``items.scalar.update`` lives in the sibling
``test_api_items_update_functions.py``. Both files share the same
mutation gate path (``mutations.prepare_update`` →
``backlog.execute_update``); the split keeps each test file under the
350-line authored-file budget.
"""

from __future__ import annotations

from copy import deepcopy
import os
import sys
import threading

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

    def test_update_status_requires_lifecycle_surface(self, client, test_db):
        conn = connect_test_db(test_db["db_path"])
        conn.execute(
            """INSERT INTO items
               (id, title, workflow_id, workflow_version_id, status, priority, project_id, project_sequence,
                created_at, updated_at, source, deploy_stage)
               VALUES (6, 'In-flight epic', 'epic', (SELECT current_version_id FROM workflows WHERE id='epic'), 'planned', 'medium', 1, 6,
                       '2026-03-01T00:00:00Z', '2026-03-02T00:00:00Z', 'user', NULL)"""
        )
        conn.commit()
        conn.close()

        resp = client.patch("/v1/items/6", json={"status": "reviewed-implementation"})
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "STATUS_UPDATE_REQUIRES_LIFECYCLE"

    def test_update_frozen(self, client, test_db):
        resp = client.patch("/v1/items/1", json={"frozen": True})
        assert resp.status_code == 200
        assert resp.json()["frozen"] is True

    def test_update_project(self, client, test_db):
        resp = client.patch("/v1/items/1", json={"project": "externalwebapp"})
        assert resp.status_code == 200
        assert resp.json()["project"] == "externalwebapp"

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
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "STATUS_UPDATE_REQUIRES_LIFECYCLE"

    def test_update_multiple_fields(self, client, test_db):
        """Multiple fields in a single PATCH request."""
        resp = client.patch(
            "/v1/items/1",
            json={
                "priority": "low",
                "title": "Updated title",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["priority"] == "low"
        assert data["title"] == "Updated title"

    def test_status_denial_preserves_item_state(self, client, test_db):
        conn = connect_test_db(test_db["db_path"])
        conn.execute(
            """INSERT INTO items
               (id, title, workflow_id, workflow_version_id, status, priority, project_id, project_sequence, rework_count,
                created_at, updated_at, source, deploy_stage)
               VALUES (7, 'Reopened issue', 'issue', (SELECT current_version_id FROM workflows WHERE id='issue'), 'done', 'medium', 1, 7, 0,
                       '2026-03-01T00:00:00Z', '2026-03-02T00:00:00Z', 'user', NULL)"""
        )
        conn.commit()
        conn.close()

        resp = client.patch("/v1/items/7", json={"status": "implementing"})
        assert resp.status_code == 409
        conn = connect_test_db(test_db["db_path"])
        row = conn.execute(
            "SELECT status, rework_count FROM items WHERE id = 7"
        ).fetchone()
        conn.close()
        assert tuple(row) == ("done", 0)

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

    def test_deployment_flow_patch_reloads_pin_after_migration(
        self,
        client,
        test_db,
        monkeypatch,
    ):
        from runtime.api.fixtures.pg_testdb import connect_test_database
        from yoke_core.api.routes import items_write
        from yoke_core.domain.builtin_workflow_definitions import (
            builtin_workflow_definition,
        )
        from yoke_core.domain.workflow_item_binding_lock import (
            lock_item_workflow_bindings,
        )
        from yoke_core.domain.workflow_item_versioning import (
            migrate_item_workflow_pin,
        )
        from yoke_core.domain.workflow_registry import publish_workflow_version

        conn = connect_test_db(test_db["db_path"])
        source_definition = deepcopy(builtin_workflow_definition("issue")["definition"])
        source_definition["stages"][0]["label"] = "PATCH migration source"
        source_definition["policies"]["path_claims"] = "optional"
        source = publish_workflow_version(
            conn,
            workflow_id="issue",
            definition=source_definition,
        )
        conn.execute(
            "UPDATE items SET workflow_version_id=%s WHERE id=1",
            (int(source["version_id"]),),
        )
        conn.commit()
        target_definition = deepcopy(source_definition)
        target_definition["stages"][0]["label"] = "PATCH migration target"
        target = publish_workflow_version(
            conn,
            workflow_id="issue",
            definition=target_definition,
        )
        db_name = str(conn.info.dbname)
        conn.close()
        migration_conn = connect_test_database(db_name)
        observed_pins = []
        original_prepare = items_write.prepare_update

        def record_pin(*args, **kwargs):
            item = kwargs.get("item") or args[0]
            observed_pins.append(item.workflow.workflow_version_id)
            return original_prepare(*args, **kwargs)

        monkeypatch.setattr(items_write, "prepare_update", record_pin)
        request_started = threading.Event()
        request_done = threading.Event()
        result = {}

        def patch_item():
            request_started.set()
            result["response"] = client.patch(
                "/v1/items/1",
                json={"deployment_flow": "test-approval-flow"},
            )
            request_done.set()

        worker = threading.Thread(target=patch_item, name="deployment-flow-patch")
        try:
            lock_item_workflow_bindings(migration_conn, (1,))
            worker.start()
            assert request_started.wait(timeout=10)
            assert not request_done.wait(timeout=0.2)
            migrate_item_workflow_pin(
                migration_conn,
                item_id=1,
                target_version=int(target["version"]),
            )
            worker.join(timeout=10)
            assert not worker.is_alive()
        finally:
            migration_conn.close()

        assert result["response"].status_code == 200
        assert observed_pins == [int(target["version_id"])]

    def test_deployment_flow_patch_serializes_before_delete(
        self, client, test_db, monkeypatch
    ):
        from runtime.api.fixtures.pg_testdb import connect_test_database
        from yoke_core.api.routes import items_write
        from yoke_core.domain.flow_crud import cmd_delete

        conn = connect_test_db(test_db["db_path"])
        conn.execute(
            "INSERT INTO deployment_flows "
            "(id, project_id, name, description, stages, on_failure, "
            "created_at, target_tier, target_environment_id, "
            "done_description, status) "
            "SELECT 'patch-delete-flow', project_id, 'PatchDelete', "
            "description, stages, "
            "on_failure, created_at, target_tier, target_environment_id, "
            "done_description, status "
            "FROM deployment_flows WHERE id='test-approval-flow'"
        )
        conn.commit()
        delete_conn = connect_test_database(str(conn.info.dbname))
        conn.close()
        patch_ready = threading.Event()
        release_patch = threading.Event()
        delete_started = threading.Event()
        delete_done = threading.Event()
        outcome = {}
        original_prepare = items_write.prepare_update

        def pause_before_write(*args, **kwargs):
            if kwargs.get("field_name") == "deployment_flow":
                patch_ready.set()
                assert release_patch.wait(timeout=10)
            return original_prepare(*args, **kwargs)

        def patch_item():
            outcome["response"] = client.patch(
                "/v1/items/1",
                json={"deployment_flow": "patch-delete-flow"},
            )

        def delete_flow():
            delete_started.set()
            try:
                outcome["delete"] = cmd_delete(delete_conn, "patch-delete-flow")
            except Exception as exc:
                outcome["delete_error"] = exc
            finally:
                delete_done.set()

        monkeypatch.setattr(items_write, "prepare_update", pause_before_write)
        patch_worker = threading.Thread(target=patch_item)
        delete_worker = threading.Thread(target=delete_flow)
        try:
            patch_worker.start()
            assert patch_ready.wait(timeout=10)
            delete_worker.start()
            assert delete_started.wait(timeout=10)
            assert not delete_done.wait(timeout=0.2)
            release_patch.set()
            patch_worker.join(timeout=10)
            delete_worker.join(timeout=10)
            assert not patch_worker.is_alive()
            assert not delete_worker.is_alive()
        finally:
            release_patch.set()
            delete_conn.close()

        assert outcome["response"].status_code == 200
        assert isinstance(outcome["delete_error"], ValueError)
        assert "still reference" in str(outcome["delete_error"])
        conn = connect_test_db(test_db["db_path"])
        row = conn.execute("SELECT deployment_flow FROM items WHERE id=1").fetchone()
        flow = conn.execute(
            "SELECT id FROM deployment_flows WHERE id='patch-delete-flow'"
        ).fetchone()
        conn.close()
        assert row[0] == "patch-delete-flow"
        assert flow is not None

    def test_update_deployed_to_handles_missing_project_capabilities_table(
        self, test_db
    ):
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
