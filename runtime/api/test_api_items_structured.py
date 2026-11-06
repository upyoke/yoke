"""Integration tests for the ``items.structured_field.*`` / ``progress_log.*`` endpoints.

Routes the FastAPI ``POST /v1/functions/call`` end-to-end via TestClient
for the five function ids registered by task 3 on the items writes
families. Claim verification is silenced by patching
:func:`yoke_core.domain.yoke_function_dispatch_claims.verify_claim`;
the DB substrate is the same on-disk fake used by
:mod:`runtime.api.domain.test_backlog_structured_write_api`.

Test classes:

- :class:`TestStructuredFieldReplaceRoute` — happy path, empty-stdin
  regression guard, GitHub-sync-degraded → 207, schema lookup.
- :class:`TestStructuredFieldAppendAddendumRoute` — happy path + empty
  rejection.
- :class:`TestStructuredFieldSectionRoutes` — section-upsert /
  section-append happy paths.
- :class:`TestProgressLogAppendRoute` — Progress Log append happy path.
"""

from __future__ import annotations

from runtime.api.api_items_structured_test_support import (_ApiSuite as _ApiSuite, _FakeDB as _FakeDB, _SCHEMA as _SCHEMA, _apply_schema as _apply_schema, _envelope as _envelope, _patch_db as _patch_db)
from runtime.api.domain.path_context_test_support import (_p as _p)


import unittest
from unittest import mock


from yoke_core.domain import (
    backlog_rendering,
)
from runtime.api.fixtures.file_test_db import (
    connect_test_db as connect_test_db,
    init_test_db as init_test_db,
)
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl as apply_fixture_ddl


class TestStructuredFieldReplaceRoute(_ApiSuite):
    def test_replace_returns_200_and_writes_field(self) -> None:
        self.db.insert_item(101, spec="old\n")
        env = _envelope(
            "items.structured_field.replace",
            payload={"field": "spec", "content": "new content\n", "source": "test"},
        )
        resp = self.client.post("/v1/functions/call", json=env)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["success"])
        # Envelope carries all required fields
        result = body["result"]
        for key in (
            "old_line_count",
            "new_line_count",
            "old_hash",
            "new_hash",
            "payload_byte_count",
            "verification",
            "github_sync",
        ):
            self.assertIn(key, result)
        self.assertEqual(self.db.fetch_field(101, "spec"), "new content\n")

    def test_empty_stdin_regression_guard(self) -> None:
        """Empty content cannot succeed for an initial spec write."""
        self.db.insert_item(101, spec=None)
        env = _envelope(
            "items.structured_field.replace",
            payload={"field": "spec", "content": ""},
        )
        resp = self.client.post("/v1/functions/call", json=env)
        self.assertEqual(resp.status_code, 422)
        body = resp.json()
        self.assertFalse(body["success"])
        self.assertEqual(body["error"]["code"], "empty_body")

    def test_github_sync_degraded_returns_207(self) -> None:
        """GitHub-sync failure surfaces as 207 + warning."""
        self.db.insert_item(101, spec="x\n")
        with (
            mock.patch.object(
                backlog_rendering,
                "_sync_body",
                return_value=(False, None),
            ),
            mock.patch.object(
                backlog_rendering,
                "_record_sync_failure",
                return_value=None,
            ),
        ):
            env = _envelope(
                "items.structured_field.replace",
                payload={"field": "spec", "content": "new body\n"},
            )
            resp = self.client.post("/v1/functions/call", json=env)
        self.assertEqual(resp.status_code, 207)
        body = resp.json()
        self.assertTrue(body["success"])
        self.assertEqual(len(body["warnings"]), 1)
        self.assertEqual(body["warnings"][0]["code"], "github_sync_degraded")

    def test_schema_endpoint_returns_jsonschema(self) -> None:
        """GET /v1/functions/schema/items.structured_field.replace."""
        resp = self.client.get(
            "/v1/functions/schema/items.structured_field.replace",
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn("properties", body)
        self.assertIn("field", body["properties"])
        self.assertIn("content", body["properties"])


if __name__ == "__main__":
    unittest.main()
