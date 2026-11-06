# ruff: noqa: F811
"""Service-client deployment_flow registry validation."""

from __future__ import annotations

from runtime.api.service_client_delivery_test_helpers_test_support import (mutation_db as mutation_db)

import json

from runtime.api.fixtures.file_test_db import connect_test_db
from runtime.api.service_client_test_support import _run_client

# Re-export the shared fixture for pytest discovery.


class TestUpdateItemFlowValidation:
    def _seed_item(self, db_path: str, item_id: int) -> None:
        conn = connect_test_db(db_path)
        try:
            conn.execute(
                """INSERT INTO items
                   (id, project_sequence, title, workflow_id, workflow_version_id, status, priority, project_id,
                    created_at, updated_at, source, deploy_stage)
                   VALUES (%s, %s, 'Test', 'issue', (SELECT current_version_id FROM workflows WHERE id='issue'), 'idea', 'medium', 1,
                           '2026-05-07T00:00:00Z', '2026-05-07T00:00:00Z',
                           'user', NULL)""",
                (item_id, item_id),
            )
            conn.commit()
        finally:
            conn.close()

    def test_update_rejects_unregistered_flow(self, mutation_db):
        self._seed_item(mutation_db["db_path"], 901)
        result = _run_client(
            [
                "validate-update",
                "YOK-901",
                "--field",
                "deployment_flow",
                "--value",
                "garbage",
            ],
            db_path=mutation_db["db_path"],
        )
        assert result.returncode == 1
        data = json.loads(result.stdout.strip())
        assert data["success"] is False
        assert data["error_code"] == "VALIDATION_ERROR"
        assert "garbage" in data["error"]
        assert "is not registered" in data["error"]
        assert data.get("preflight_only") is True

    def test_update_rejects_literal_none_string(self, mutation_db):
        self._seed_item(mutation_db["db_path"], 902)
        result = _run_client(
            [
                "validate-update",
                "YOK-902",
                "--field",
                "deployment_flow",
                "--value",
                "none",
            ],
            db_path=mutation_db["db_path"],
        )
        assert result.returncode == 1
        data = json.loads(result.stdout.strip())
        assert data["success"] is False
        assert "'none'" in data["error"]

    def test_update_accepts_registered_flow(self, mutation_db):
        self._seed_item(mutation_db["db_path"], 903)
        result = _run_client(
            [
                "validate-update",
                "YOK-903",
                "--field",
                "deployment_flow",
                "--value",
                "test-flow",
            ],
            db_path=mutation_db["db_path"],
        )
        assert result.returncode == 0
        data = json.loads(result.stdout.strip())
        assert data["success"] is True

    def test_update_accepts_null_sentinel(self, mutation_db):
        self._seed_item(mutation_db["db_path"], 904)
        result = _run_client(
            [
                "validate-update",
                "YOK-904",
                "--field",
                "deployment_flow",
                "--value",
                "null",
            ],
            db_path=mutation_db["db_path"],
        )
        assert result.returncode == 0
        data = json.loads(result.stdout.strip())
        assert data["success"] is True
