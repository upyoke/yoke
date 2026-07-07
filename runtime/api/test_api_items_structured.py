"""Integration tests for the ``items.structured_field.*`` / ``progress_log.*`` endpoints.

Routes the FastAPI ``POST /v1/functions/call`` end-to-end via TestClient
for the five function ids registered by task 3 on the items writes
families. Claim verification is silenced by patching
:func:`yoke_core.domain.yoke_function_dispatch_claims.verify_claim`;
the DB substrate is the same on-disk fake used by
:mod:`runtime.api.domain.test_backlog_structured_write_api`.

Test classes:

- :class:`TestStructuredFieldReplaceRoute` — happy path, AC-3.6
  regression, AC-3.10 GitHub-sync-degraded → 207, AC-3.12 schema lookup.
- :class:`TestStructuredFieldAppendAddendumRoute` — happy path + empty
  rejection.
- :class:`TestStructuredFieldSectionRoutes` — section-upsert /
  section-append happy paths.
- :class:`TestProgressLogAppendRoute` — Progress Log append happy path.
"""

from __future__ import annotations

import os
import unittest
from typing import Optional
from unittest import mock

import pytest
from fastapi.testclient import TestClient

from runtime.api.auth_test_helpers import mint_api_auth_context
from yoke_core.domain import (
    backlog_queries,
    backlog_rendering,
    backlog_structured_write_op,
    db_backend,
    item_field_transform,
    sections,
    yoke_function_dispatch as dispatch_module,
    yoke_function_dispatch_events as events_module,
)
from yoke_core.domain.handlers import items_structured_field
from yoke_core.domain.handlers.__init_register__ import register_all_handlers
from yoke_core.domain.yoke_function_registry import (
    reset_registry_for_tests,
)
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
from yoke_core.api.main import app


_SCHEMA = """
CREATE TABLE items (
    id INTEGER PRIMARY KEY,
    spec TEXT, design_spec TEXT, technical_plan TEXT,
    worktree_plan TEXT, shepherd_log TEXT,
    shepherd_caveats TEXT, test_results TEXT, deploy_log TEXT,
    browser_qa_metadata TEXT, db_mutation_profile TEXT,
    db_compatibility_attestation TEXT, architecture_impact TEXT,
    updated_at TEXT, spec_updated_at TEXT, spec_updated_by TEXT
);
CREATE TABLE item_sections (
    item_id INTEGER, section_name TEXT, content TEXT,
    ordering INTEGER, source TEXT DEFAULT 'operator',
    created_at TEXT, updated_at TEXT,
    PRIMARY KEY(item_id, section_name)
);
CREATE TABLE harness_sessions (
    session_id TEXT PRIMARY KEY,
    actor_id TEXT
);
"""


def _apply_schema() -> None:
    """Zero-arg ``apply_schema`` strategy for :func:`init_test_db`.

    Resolves its connection through the backend factory and applies the schema
    through the native fixture helper.
    """
    conn = db_backend.connect()
    try:
        apply_fixture_ddl(conn, _SCHEMA)
    finally:
        conn.close()


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


class _FakeDB:
    """Backend-aware handle on a :func:`init_test_db` per-test database.

    Reads/writes go through :func:`connect_test_db` so the same bodies hit the
    right engine (the ``db_path`` token is the SQLite file or, on Postgres, an
    ignored placeholder whose real target is the repointed DSN).
    """

    def __init__(self, db_path: str) -> None:
        self.path = db_path

    def insert_item(self, item_id: int, **fields: Optional[str]) -> None:
        cols = ["id"] + list(fields.keys())
        conn = connect_test_db(self.path)
        try:
            marks = ", ".join([_p(conn)] * len(cols))
            conn.execute(
                f"INSERT INTO items ({', '.join(cols)}) VALUES ({marks})",
                (item_id, *fields.values()),
            )
            conn.commit()
        finally:
            conn.close()

    def fetch_field(self, item_id: int, field: str) -> Optional[str]:
        conn = connect_test_db(self.path)
        try:
            p = _p(conn)
            row = conn.execute(
                f"SELECT {field} FROM items WHERE id = {p}", (item_id,),
            ).fetchone()
        finally:
            conn.close()
        return row[0] if row else None


def _patch_db(test: unittest.TestCase, db: _FakeDB) -> None:
    from yoke_core.domain import db_helpers as _db_helpers
    targets = [
        (backlog_queries, "_resolve_write_db_path", db.path),
        (backlog_queries, "_assert_write_db_ready", None),
        (backlog_structured_write_op, "_resolve_write_db_path", db.path),
        (backlog_structured_write_op, "_assert_write_db_ready", None),
        (item_field_transform, "_resolve_write_db_path", db.path),
        (items_structured_field, "_resolve_write_db_path", db.path),
        (backlog_rendering, "_render_body", True),
        (backlog_rendering, "_sync_body", (True, "full")),
        (backlog_rendering, "_maybe_rebuild_board", None),
        (sections, "_render_fn", 0),
        (sections, "_emit_event_fn", None),
        (_db_helpers, "resolve_db_path", db.path),
    ]
    for module, name, value in targets:
        patcher = mock.patch.object(module, name, return_value=value)
        patcher.start()
        test.addCleanup(patcher.stop)


def _envelope(function_id: str, *, item_id: int = 101, **overrides):
    base = {
        "function": function_id,
        "version": "v1",
        "actor": {"actor_id": "op", "session_id": "s-1"},
        "target": {"kind": "item", "item_id": item_id, "project_id": "yoke"},
        "payload": {},
        "preconditions": {},
        "options": {},
    }
    base.update(overrides)
    return base


class _ApiSuite(unittest.TestCase):
    @pytest.fixture(autouse=True)
    def _suite(self, tmp_path):
        # The seam owns the per-test DB lifecycle (a file on SQLite, a
        # disposable per-test database on Postgres). YOKE_DB is bound so both
        # the dispatched handlers and the _FakeDB helpers hit the same DB; on
        # Postgres the binding is inert and init_test_db keeps YOKE_PG_DSN
        # repointed at the per-test database for the context.
        with init_test_db(tmp_path, apply_schema=_apply_schema) as db_path:
            with mock.patch.dict(
                os.environ, {"YOKE_DB": db_path}, clear=False
            ):
                reset_registry_for_tests()
                register_all_handlers()
                self._event_patch = mock.patch.object(
                    events_module, "emit_event")
                self._event_patch.start()
                self._idem_patch = mock.patch.object(
                    dispatch_module, "_idempotency_lookup", return_value=None,
                )
                self._idem_patch.start()
                # The claim verification path consults the real DB; in tests we
                # silence it because the fake DB has no harness_sessions rows.
                self._claim_patch = mock.patch.object(
                    dispatch_module, "verify_claim", return_value=None,
                )
                self._claim_patch.start()
                self.db = _FakeDB(db_path)
                _patch_db(self, self.db)
                self.client = TestClient(app)
                conn = connect_test_db(db_path)
                try:
                    auth = mint_api_auth_context(conn)
                finally:
                    conn.close()
                self.client.headers.update(auth.headers)
                try:
                    yield
                finally:
                    self._event_patch.stop()
                    self._idem_patch.stop()
                    self._claim_patch.stop()
                    reset_registry_for_tests()


class TestStructuredFieldReplaceRoute(_ApiSuite):
    def test_replace_returns_200_and_writes_field(self) -> None:
        self.db.insert_item(101, spec="old\n")
        env = _envelope(
            "items.structured_field.replace",
            payload={"field": "spec", "content": "new content\n",
                     "source": "test"},
        )
        resp = self.client.post("/v1/functions/call", json=env)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["success"])
        # AC-3.5: envelope carries all required fields
        result = body["result"]
        for key in (
            "old_line_count", "new_line_count", "old_hash", "new_hash",
            "payload_byte_count", "verification", "github_sync",
        ):
            self.assertIn(key, result)
        self.assertEqual(self.db.fetch_field(101, "spec"), "new content\n")

    def test_empty_stdin_regression_guard(self) -> None:
        """AC-3.6: empty content cannot succeed for an initial spec write."""
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
        """AC-3.10: GitHub-sync failure surfaces as 207 + warning."""
        self.db.insert_item(101, spec="x\n")
        with mock.patch.object(
            backlog_rendering, "_sync_body", return_value=(False, None),
        ), mock.patch.object(
            backlog_rendering, "_record_sync_failure", return_value=None,
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
        """AC-3.12: GET /v1/functions/schema/items.structured_field.replace."""
        resp = self.client.get(
            "/v1/functions/schema/items.structured_field.replace",
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn("properties", body)
        self.assertIn("field", body["properties"])
        self.assertIn("content", body["properties"])


class TestStructuredFieldAppendAddendumRoute(_ApiSuite):
    def test_append_addendum_happy_path(self) -> None:
        self.db.insert_item(101, spec="# Spec\n\nbody\n")
        env = _envelope(
            "items.structured_field.append_addendum",
            payload={"field": "spec", "heading": "Refinement Addendum",
                     "content": "more"},
        )
        resp = self.client.post("/v1/functions/call", json=env)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["success"])
        self.assertTrue(body["result"]["changed"])
        self.assertIn("## Refinement Addendum",
                      self.db.fetch_field(101, "spec"))

    def test_append_addendum_empty_rejected(self) -> None:
        self.db.insert_item(101, spec="x\n")
        env = _envelope(
            "items.structured_field.append_addendum",
            payload={"field": "spec", "heading": "X", "content": ""},
        )
        resp = self.client.post("/v1/functions/call", json=env)
        # The domain owner's "refusing addendum with empty content" maps
        # through _classify_write_error → "empty_body" → HTTP 422.
        self.assertEqual(resp.status_code, 422)
        body = resp.json()
        self.assertFalse(body["success"])
        self.assertEqual(body["error"]["code"], "empty_body")


class TestStructuredFieldSectionRoutes(_ApiSuite):
    def test_section_upsert_writes_section_row(self) -> None:
        self.db.insert_item(101, spec="x\n")
        env = _envelope(
            "items.structured_field.section_upsert",
            payload={"section": "Notes", "content": "note body\n"},
        )
        resp = self.client.post("/v1/functions/call", json=env)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["success"])
        self.assertEqual(body["result"]["section"], "Notes")

    def test_section_append_writes_entry(self) -> None:
        self.db.insert_item(101, spec="x\n")
        env = _envelope(
            "items.structured_field.section_append",
            payload={"section": "Progress Log",
                     "headline": "checkpoint", "content": "body"},
        )
        resp = self.client.post("/v1/functions/call", json=env)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["success"])


class TestProgressLogAppendRoute(_ApiSuite):
    def test_progress_log_append_happy_path(self) -> None:
        """AC-3.9: append into 'Progress Log' with ordering=200."""
        self.db.insert_item(101, spec="x\n")
        env = _envelope(
            "items.progress_log.append",
            payload={"headline": "checkpoint", "content": "body"},
        )
        resp = self.client.post("/v1/functions/call", json=env)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["success"])
        self.assertEqual(body["result"]["section"], "Progress Log")


if __name__ == "__main__":
    unittest.main()
