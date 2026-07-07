"""Integration tests for the Yoke function-call FastAPI routes.

Covers the three new endpoints (`POST /v1/functions/call`,
`GET /v1/functions/registry`, `GET /v1/functions/schema/{id}`) end-to-end
via FastAPI's TestClient.
"""

from __future__ import annotations

import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from pydantic import BaseModel

from runtime.api.auth_test_helpers import mint_api_auth_context
from yoke_core.domain import yoke_function_dispatch as dispatch_module
from yoke_core.domain import yoke_function_dispatch_events as events_module
from yoke_core.domain.api_tokens import TOKEN_PREFIX, mint_token, revoke_token
from yoke_contracts.api.function_call import (
    FunctionWarning,
    HandlerOutcome,
)
from yoke_core.domain.yoke_function_registry import (
    register,
    reset_registry_for_tests,
)
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from runtime.api.fixtures.schema_ddl import SCHEMA_DDL, apply_fixture_ddl
from yoke_core.api.main import app
from runtime.api.test_api_helpers import _install_overrides


class _Req(BaseModel):
    pass


class _Resp(BaseModel):
    pass


def _stable_kwargs(**overrides):
    base = {
        "stability": "stable",
        "owner_module": "yoke_core.domain.test_module",
        "target_kinds": ["item"],
        "side_effects": [],
        "emitted_event_names": ["FakeEvent"],
        "guardrails": [],
        "adapter_status": "live",
    }
    base.update(overrides)
    return base


def _envelope(function_id: str, **overrides):
    base = {
        "function": function_id,
        "version": "v1",
        "actor": {"actor_id": "op", "session_id": "s-1"},
        "target": {"kind": "item", "item_id": 42, "project_id": "yoke"},  # resolvable target
        "payload": {},
        "preconditions": {},
        "options": {},
    }
    base.update(overrides)
    return base


def _ok_handler(_request):
    return HandlerOutcome(result_payload={"ok": True}, primary_success=True)


def _actor_echo_handler(request):
    return HandlerOutcome(
        result_payload={"actor_id": request.actor.actor_id},
        primary_success=True,
    )


def _warning_handler(_request):
    return HandlerOutcome(
        result_payload={"ok": True},
        primary_success=True,
        warnings=[
            FunctionWarning(
                code="github_sync_degraded",
                step="github_sync",
                detail="rate-limited",
            )
        ],
    )


class _ApiSuite(unittest.TestCase):
    def setUp(self) -> None:
        self._stack = ExitStack()
        self._tmp_dir = self._stack.enter_context(tempfile.TemporaryDirectory())
        self._db_path = self._stack.enter_context(
            init_test_db(
                Path(self._tmp_dir),
                apply_schema=lambda: apply_fixture_ddl_from_active_db(),
            )
        )
        self._stack.enter_context(_install_overrides(self._db_path))
        conn = connect_test_db(self._db_path)
        try:
            self._auth = mint_api_auth_context(conn)
        finally:
            conn.close()
        reset_registry_for_tests()
        # Silence event emission so the API endpoint does not require the
        # full events table during integration tests.
        self._event_patch = patch.object(events_module, "emit_event")
        self._event_patch.start()
        # Suppress the idempotency-ledger lookup so a stale
        # `function_call_ledger` row never replays unrelated request_ids
        # in integration tests.
        self._idem_patch = patch.object(
            dispatch_module, "_idempotency_lookup", return_value=None,
        )
        self._idem_patch.start()
        # Reuse the package-level app singleton; the test registers its
        # own ids in the cleared registry. Skip lifespan because it would
        # call register_all_handlers() against the already-cleared registry.
        self._client = TestClient(app)

    def tearDown(self) -> None:
        self._client.close()
        self._event_patch.stop()
        self._idem_patch.stop()
        reset_registry_for_tests()
        self._stack.close()

    @property
    def _headers(self) -> dict[str, str]:
        return self._auth.headers


def apply_fixture_ddl_from_active_db() -> None:
    from yoke_core.domain import db_backend

    conn = db_backend.connect()
    try:
        apply_fixture_ddl(conn, SCHEMA_DDL)
    finally:
        conn.close()


class TestRegistryEndpoint(_ApiSuite):
    def test_registry_endpoint_returns_registered_ids(self):
        register(
            "items.scalar.update", _ok_handler, _Req, _Resp,
            **_stable_kwargs(),
        )
        resp = self._client.get("/v1/functions/registry", headers=self._headers)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        ids = [e["function_id"] for e in body["functions"]]
        self.assertIn("items.scalar.update", ids)


class TestSchemaEndpoint(_ApiSuite):
    def test_schema_endpoint_returns_404_for_unknown_id(self):
        resp = self._client.get(
            "/v1/functions/schema/items.structured_field.replace",
            headers=self._headers,
        )
        self.assertEqual(resp.status_code, 404)

    def test_schema_endpoint_returns_json_schema(self):
        register(
            "items.scalar.update", _ok_handler, _Req, _Resp,
            **_stable_kwargs(),
        )
        resp = self._client.get(
            "/v1/functions/schema/items.scalar.update",
            headers=self._headers,
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn("properties", body)


class TestCallEndpoint(_ApiSuite):
    def test_call_unknown_function_returns_404(self):
        resp = self._client.post(
            "/v1/functions/call",
            json=_envelope("missing.family.op"),
            headers=self._headers,
        )
        self.assertEqual(resp.status_code, 404)
        body = resp.json()
        self.assertEqual(body["error"]["code"], "function_not_registered")

    def test_call_envelope_invalid_returns_422(self):
        resp = self._client.post(
            "/v1/functions/call",
            json={"function": "missing.family.op"},
            headers=self._headers,
        )
        self.assertEqual(resp.status_code, 422)
        body = resp.json()
        self.assertEqual(body["error"]["code"], "envelope_invalid")

    def test_call_happy_path_returns_200(self):
        register(
            "items.scalar.update", _ok_handler, _Req, _Resp,
            **_stable_kwargs(),
        )
        resp = self._client.post(
            "/v1/functions/call",
            json=_envelope("items.scalar.update"),
            headers=self._headers,
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["success"])
        self.assertEqual(body["result"], {"ok": True})

    def test_call_overwrites_envelope_actor_id_with_verified_token_actor_id(self):
        register(
            "items.actor.echo", _actor_echo_handler, _Req, _Resp,
            **_stable_kwargs(),
        )
        resp = self._client.post(
            "/v1/functions/call",
            json=_envelope(
                "items.actor.echo",
                actor={"actor_id": "spoofed", "session_id": "s-1"},
            ),
            headers=self._headers,
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertTrue(body["success"])
        self.assertEqual(body["result"]["actor_id"], str(self._auth.actor_id))

    def test_call_partial_state_warnings_returns_207(self):
        register(
            "items.warned.op", _warning_handler, _Req, _Resp,
            **_stable_kwargs(),
        )
        resp = self._client.post(
            "/v1/functions/call",
            json=_envelope("items.warned.op"),
            headers=self._headers,
        )
        self.assertEqual(resp.status_code, 207)
        body = resp.json()
        self.assertTrue(body["success"])
        self.assertEqual(len(body["warnings"]), 1)
        self.assertEqual(body["warnings"][0]["code"], "github_sync_degraded")


class TestHttpAuthBoundary(_ApiSuite):
    def _register_ok_function(self) -> None:
        register(
            "items.scalar.update", _ok_handler, _Req, _Resp,
            **_stable_kwargs(),
        )

    def test_health_remains_public(self):
        resp = self._client.get("/v1/health")
        self.assertEqual(resp.status_code, 200)

    def test_docs_redoc_and_openapi_are_disabled(self):
        for path in ("/docs", "/redoc", "/openapi.json"):
            with self.subTest(path=path):
                resp = self._client.get(path, headers=self._headers)
                self.assertEqual(resp.status_code, 404)

    def test_registry_requires_bearer_token(self):
        resp = self._client.get("/v1/functions/registry")
        self.assertEqual(resp.status_code, 401)

    def test_schema_requires_bearer_token(self):
        self._register_ok_function()
        resp = self._client.get("/v1/functions/schema/items.scalar.update")
        self.assertEqual(resp.status_code, 401)

    def test_call_requires_bearer_token(self):
        self._register_ok_function()
        resp = self._client.post(
            "/v1/functions/call",
            json=_envelope("items.scalar.update"),
        )
        self.assertEqual(resp.status_code, 401)

    def test_call_rejects_malformed_authorization_header(self):
        self._register_ok_function()
        resp = self._client.post(
            "/v1/functions/call",
            json=_envelope("items.scalar.update"),
            headers={"Authorization": "Token not-bearer"},
        )
        self.assertEqual(resp.status_code, 401)

    def test_call_rejects_unknown_token(self):
        self._register_ok_function()
        resp = self._client.post(
            "/v1/functions/call",
            json=_envelope("items.scalar.update"),
            headers={"Authorization": f"Bearer {TOKEN_PREFIX}unknown"},
        )
        self.assertEqual(resp.status_code, 401)

    def test_call_rejects_revoked_token(self):
        self._register_ok_function()
        conn = connect_test_db(self._db_path)
        try:
            revoke_token(
                conn,
                token_id=self._auth.token.token_id,
                actor_id=self._auth.actor_id,
            )
        finally:
            conn.close()
        resp = self._client.post(
            "/v1/functions/call",
            json=_envelope("items.scalar.update"),
            headers=self._headers,
        )
        self.assertEqual(resp.status_code, 401)

    def test_call_rejects_expired_token(self):
        self._register_ok_function()
        conn = connect_test_db(self._db_path)
        try:
            expired = mint_token(
                conn,
                actor_id=self._auth.actor_id,
                name="expired-test-token",
                expires_at="2020-01-01T00:00:00Z",
            )
        finally:
            conn.close()
        resp = self._client.post(
            "/v1/functions/call",
            json=_envelope("items.scalar.update"),
            headers={"Authorization": f"Bearer {expired.raw_token}"},
        )
        self.assertEqual(resp.status_code, 401)


if __name__ == "__main__":
    unittest.main()
