"""HTTP-boundary backstop for server-side item-ref resolution.

The relay contract's CI backstop: an https-only client carries raw
``PREFIX-N`` / bare-number refs on ``target.item_ref`` and the cloud
boundary (bearer auth -> dispatcher -> resolver) turns them into
``target.item_id`` server-side. Exercises ``POST /v1/functions/call``
through the real FastAPI app with a real minted token — the same path
a no-checkout machine uses.
"""

from __future__ import annotations

import os
import unittest
from unittest import mock

import pytest
from fastapi.testclient import TestClient

from yoke_core.api.main import app
from runtime.api.auth_test_helpers import mint_api_auth_context
from yoke_core.domain import db_backend
from yoke_core.domain import events as events_module
from yoke_core.domain import yoke_function_dispatch as dispatch_module
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
from yoke_core.domain.yoke_function_registry import (
    reset_registry_for_tests,
)
from yoke_core.domain.handlers.__init_register__ import register_all_handlers
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


_SCHEMA = """
CREATE TABLE items (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL DEFAULT 1,
    project_sequence INTEGER NOT NULL,
    title TEXT DEFAULT '',
    type TEXT DEFAULT 'issue',
    status TEXT DEFAULT 'idea',
    priority TEXT DEFAULT 'medium',
    flow TEXT, rework_count INTEGER DEFAULT 0,
    frozen INTEGER DEFAULT 0, github_issue INTEGER,
    deployed_to TEXT, worktree TEXT, merged_at TEXT,
    created_at TEXT, updated_at TEXT, source TEXT,
    deployment_flow TEXT, deploy_stage TEXT,
    UNIQUE(project_id, project_sequence)
);
CREATE TABLE harness_sessions (
    session_id TEXT PRIMARY KEY,
    actor_id TEXT,
    current_item_id TEXT,
    recent_item_id TEXT
);
"""


def _apply_schema() -> None:
    conn = db_backend.connect()
    try:
        apply_fixture_ddl(conn, _SCHEMA)
    finally:
        conn.close()


def _envelope(target: dict) -> dict:
    return {
        "function": "items.get.run",
        "version": "v1",
        "actor": {"actor_id": None, "session_id": "s-relay"},
        "target": target,
        "payload": {"fields": ["status"]},
        "preconditions": {},
        "options": {},
    }


class TestItemRefOverHttpBoundary(unittest.TestCase):
    @pytest.fixture(autouse=True)
    def _suite(self, tmp_path):
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
                conn = connect_test_db(db_path)
                try:
                    auth = mint_api_auth_context(conn)
                    p = (
                        "%s"
                        if db_backend.connection_is_postgres(conn)
                        else "?"
                    )
                    conn.execute(
                        "INSERT INTO items (id, project_id, project_sequence,"
                        f" title, status) VALUES ({p}, {p}, {p}, {p}, {p})",
                        (9001, 1, 4242, "relay backstop", "done"),
                    )
                    conn.commit()
                finally:
                    conn.close()
                self.client = TestClient(app)
                self.client.headers.update(auth.headers)
                try:
                    yield
                finally:
                    self._idem_patch.stop()
                    self._event_patch.stop()
                    reset_registry_for_tests()

    def test_prefix_ref_resolves_server_side(self) -> None:
        resp = self.client.post(
            "/v1/functions/call",
            json=_envelope({"kind": "item", "item_ref": "YOK-4242"}),
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["success"])
        self.assertEqual(body["result"]["item_id"], 9001)
        self.assertEqual(body["result"]["fields"]["status"], "done")

    def test_bare_number_with_project_context_resolves(self) -> None:
        resp = self.client.post(
            "/v1/functions/call",
            json=_envelope(
                {"kind": "item", "item_ref": "4242", "project_id": "yoke"},
            ),
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["success"])
        self.assertEqual(body["result"]["item_id"], 9001)

    def test_bare_number_without_context_is_typed_error(self) -> None:
        resp = self.client.post(
            "/v1/functions/call",
            json=_envelope({"kind": "item", "item_ref": "4242"}),
        )
        body = resp.json()
        self.assertFalse(body["success"])
        self.assertEqual(body["error"]["code"], "item_ref_unresolved")

    def test_unknown_ref_is_typed_error(self) -> None:
        resp = self.client.post(
            "/v1/functions/call",
            json=_envelope({"kind": "item", "item_ref": "YOK-999999"}),
        )
        body = resp.json()
        self.assertFalse(body["success"])
        self.assertEqual(body["error"]["code"], "item_ref_unresolved")


if __name__ == "__main__":
    unittest.main()
