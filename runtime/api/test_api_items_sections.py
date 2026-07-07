"""Integration tests for the ``items.section.*`` endpoints.

Routes the FastAPI ``POST /v1/functions/call`` end-to-end via TestClient
for the three function ids registered by task 3 on the items.section
family: ``upsert``, ``delete``, ``get``. The DB substrate is the same
on-disk fake used by :mod:`runtime.api.test_api_items_structured`.
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
from yoke_core.domain.yoke_function_registry import reset_registry_for_tests
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
from yoke_core.api.main import app


_SCHEMA = """
CREATE TABLE items (
    id INTEGER PRIMARY KEY,
    spec TEXT, updated_at TEXT, spec_updated_at TEXT, spec_updated_by TEXT
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
            p = "%s" if db_backend.connection_is_postgres(conn) else "?"
            marks = ", ".join([p] * len(cols))
            conn.execute(
                f"INSERT INTO items ({', '.join(cols)}) VALUES ({marks})",
                (item_id, *fields.values()),
            )
            conn.commit()
        finally:
            conn.close()

    def fetch_section(self, item_id: int, name: str) -> Optional[str]:
        conn = connect_test_db(self.path)
        try:
            p = "%s" if db_backend.connection_is_postgres(conn) else "?"
            row = conn.execute(
                "SELECT content FROM item_sections "
                f"WHERE item_id={p} AND section_name={p}",
                (item_id, name),
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


def _envelope(function_id: str, *, item_id: int = 101, section_name: str,
              **overrides):
    base = {
        "function": function_id,
        "version": "v1",
        "actor": {"actor_id": "op", "session_id": "s-1"},
        "target": {
            "kind": "section",
            "item_id": item_id,
            "section_name": section_name,
            "project_id": "yoke",
        },
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


class TestSectionUpsertRoute(_ApiSuite):
    def test_upsert_inserts_section_row(self) -> None:
        self.db.insert_item(101, spec="x\n")
        env = _envelope(
            "items.section.upsert", section_name="Notes",
            payload={"content": "note body\n", "ordering": 200},
        )
        resp = self.client.post("/v1/functions/call", json=env)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["success"])
        self.assertEqual(body["result"]["section_name"], "Notes")
        self.assertEqual(self.db.fetch_section(101, "Notes"), "note body\n")

    def test_upsert_replaces_existing_section(self) -> None:
        self.db.insert_item(101, spec="x\n")
        # First write
        env = _envelope(
            "items.section.upsert", section_name="Notes",
            payload={"content": "first\n"},
        )
        self.client.post("/v1/functions/call", json=env)
        # Replace
        env["payload"] = {"content": "second\n"}
        resp = self.client.post("/v1/functions/call", json=env)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.db.fetch_section(101, "Notes"), "second\n")

    def test_empty_content_rejected(self) -> None:
        self.db.insert_item(101, spec="x\n")
        env = _envelope(
            "items.section.upsert", section_name="Notes",
            payload={"content": ""},
        )
        resp = self.client.post("/v1/functions/call", json=env)
        # empty_body maps to HTTP 422 per AC-3.2 wiring.
        self.assertEqual(resp.status_code, 422)
        body = resp.json()
        self.assertFalse(body["success"])
        self.assertEqual(body["error"]["code"], "empty_body")

    def test_structured_field_name_rejected(self) -> None:
        """A section name that collides with a structured field is refused."""
        self.db.insert_item(101, spec="x\n")
        env = _envelope(
            "items.section.upsert", section_name="spec",
            payload={"content": "body"},
        )
        resp = self.client.post("/v1/functions/call", json=env)
        self.assertEqual(resp.status_code, 422)


class TestSectionDeleteRoute(_ApiSuite):
    def test_delete_removes_row(self) -> None:
        self.db.insert_item(101, spec="x\n")
        # Insert first
        env_up = _envelope(
            "items.section.upsert", section_name="Notes",
            payload={"content": "body\n"},
        )
        self.client.post("/v1/functions/call", json=env_up)
        # Delete
        env = _envelope(
            "items.section.delete", section_name="Notes",
            payload={},
        )
        resp = self.client.post("/v1/functions/call", json=env)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["success"])
        self.assertTrue(body["result"]["deleted"])
        self.assertIsNone(self.db.fetch_section(101, "Notes"))

    def test_delete_missing_section_succeeds_with_deleted_false(self) -> None:
        self.db.insert_item(101, spec="x\n")
        env = _envelope(
            "items.section.delete", section_name="DoesNotExist",
            payload={},
        )
        resp = self.client.post("/v1/functions/call", json=env)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["success"])
        self.assertFalse(body["result"]["deleted"])


class TestSectionGetRoute(_ApiSuite):
    def test_get_returns_content(self) -> None:
        self.db.insert_item(101, spec="x\n")
        env_up = _envelope(
            "items.section.upsert", section_name="Notes",
            payload={"content": "note body\n"},
        )
        self.client.post("/v1/functions/call", json=env_up)
        env = _envelope(
            "items.section.get", section_name="Notes",
            payload={},
        )
        resp = self.client.post("/v1/functions/call", json=env)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["success"])
        self.assertTrue(body["result"]["found"])
        self.assertEqual(body["result"]["content"], "note body\n")

    def test_get_missing_returns_404_code(self) -> None:
        self.db.insert_item(101, spec="x\n")
        env = _envelope(
            "items.section.get", section_name="DoesNotExist",
            payload={},
        )
        resp = self.client.post("/v1/functions/call", json=env)
        self.assertEqual(resp.status_code, 404)
        body = resp.json()
        self.assertEqual(body["error"]["code"], "target_not_found")


if __name__ == "__main__":
    unittest.main()
