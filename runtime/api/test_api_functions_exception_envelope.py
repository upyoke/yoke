"""Regression coverage for typed envelopes on function-call exceptions."""

from __future__ import annotations

import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from runtime.api.auth_test_helpers import mint_api_auth_context
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from runtime.api.fixtures.schema_ddl import SCHEMA_DDL, apply_fixture_ddl
from yoke_core.api.main import app
from runtime.api.test_api_helpers import _install_overrides


def _apply_fixture_ddl_from_active_db() -> None:
    from yoke_core.domain import db_backend

    conn = db_backend.connect()
    try:
        apply_fixture_ddl(conn, SCHEMA_DDL)
    finally:
        conn.close()


class TestFunctionCallExceptionEnvelope(unittest.TestCase):
    def setUp(self) -> None:
        self._stack = ExitStack()
        tmp_dir = self._stack.enter_context(tempfile.TemporaryDirectory())
        self._db_path = self._stack.enter_context(
            init_test_db(
                Path(tmp_dir),
                apply_schema=_apply_fixture_ddl_from_active_db,
            )
        )
        self._stack.enter_context(_install_overrides(self._db_path))
        conn = connect_test_db(self._db_path)
        try:
            self._auth = mint_api_auth_context(conn)
        finally:
            conn.close()
        self._client = TestClient(app)

    def tearDown(self) -> None:
        self._client.close()
        self._stack.close()

    def test_dispatch_exception_returns_function_call_response(self) -> None:
        envelope = {
            "function": "items.structured_field.append_addendum",
            "version": "v1",
            "actor": {"actor_id": "op", "session_id": "s-1"},
            "target": {"kind": "item", "item_id": 1902},
            "request_id": "req-explodes",
            "payload": {},
        }
        with mock.patch(
            "yoke_core.api.routes.functions.dispatch",
            side_effect=RuntimeError("repo root missing"),
        ):
            response = self._client.post(
                "/v1/functions/call",
                json=envelope,
                headers=self._auth.headers,
            )

        self.assertEqual(response.status_code, 500)
        body = response.json()
        self.assertFalse(body["success"])
        self.assertEqual(body["function"], envelope["function"])
        self.assertEqual(body["request_id"], "req-explodes")
        self.assertEqual(body["error"]["code"], "handler_exception")
        self.assertIn("repo root missing", body["error"]["message"])

    def test_pre_dispatch_authz_exception_does_not_escape_route(self) -> None:
        envelope = {
            "function": "missing.family.op",
            "version": "v1",
            "actor": {"actor_id": "op", "session_id": "s-1"},
            "target": {"kind": "global"},
            "request_id": "req-telemetry-explodes",
            "payload": {},
        }
        with mock.patch(
            "yoke_core.api.routes.functions.lookup",
            side_effect=RuntimeError("telemetry broke"),
        ):
            response = self._client.post(
                "/v1/functions/call",
                json=envelope,
                headers=self._auth.headers,
            )

        self.assertEqual(response.status_code, 404)
        body = response.json()
        self.assertFalse(body["success"])
        self.assertEqual(body["function"], envelope["function"])
        self.assertEqual(body["request_id"], "req-telemetry-explodes")
        self.assertEqual(body["error"]["code"], "function_not_registered")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
