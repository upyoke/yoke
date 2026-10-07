"""Regression checks for api function http auth."""

from __future__ import annotations

from runtime.api.test_api_yoke_functions import (
    TOKEN_PREFIX as TOKEN_PREFIX,
    _ApiSuite as _ApiSuite,
    _Req as _Req,
    _Resp as _Resp,
    _envelope as _envelope,
    _ok_handler as _ok_handler,
    _stable_kwargs as _stable_kwargs,
    connect_test_db as connect_test_db,
    mint_token as mint_token,
    register as register,
    revoke_token as revoke_token,
)


class TestHttpAuthBoundary(_ApiSuite):
    def _register_ok_function(self) -> None:
        register(
            "items.scalar.update",
            _ok_handler,
            _Req,
            _Resp,
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
