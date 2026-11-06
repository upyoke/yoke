"""Integration tests for the Yoke function-call FastAPI routes.

Covers the three new endpoints (`POST /v1/functions/call`,
`GET /v1/functions/registry`, `GET /v1/functions/schema/{id}`) end-to-end
via FastAPI's TestClient.
"""

from __future__ import annotations

from runtime.api.api_yoke_functions_test_support import (_ApiSuite as _ApiSuite, _FIXTURE_ITEM_REF as _FIXTURE_ITEM_REF, _Req as _Req, _Resp as _Resp, _actor_echo_handler as _actor_echo_handler, _envelope as _envelope, _stable_kwargs as _stable_kwargs)
from runtime.api.domain.yoke_function_actor_identity_dispatch_test_support import (_ok_handler as _ok_handler)


import unittest


from yoke_core.domain.api_tokens import (
    TOKEN_PREFIX as TOKEN_PREFIX,
    mint_token as mint_token,
    revoke_token as revoke_token,
)
from yoke_contracts.api.function_call import (
    FunctionWarning,
    HandlerOutcome,
)
from yoke_core.domain.yoke_function_registry import (
    register as register,
)
from runtime.api.fixtures.file_test_db import (
    connect_test_db as connect_test_db,
    init_test_db as init_test_db,
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


class TestRegistryEndpoint(_ApiSuite):
    def test_registry_endpoint_returns_registered_ids(self):
        register(
            "items.scalar.update",
            _ok_handler,
            _Req,
            _Resp,
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
            "items.scalar.update",
            _ok_handler,
            _Req,
            _Resp,
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
            "items.scalar.update",
            _ok_handler,
            _Req,
            _Resp,
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
            "items.actor.echo",
            _actor_echo_handler,
            _Req,
            _Resp,
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
            "items.warned.op",
            _warning_handler,
            _Req,
            _Resp,
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


if __name__ == "__main__":
    unittest.main()
