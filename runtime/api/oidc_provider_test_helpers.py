"""In-process stub OpenID Connect provider for sign-in door tests.

A threaded ``http.server`` serving the three provider surfaces the door
consumes — discovery, JWKS, and the token endpoint — signing id_tokens
RS256 with an RSA keypair minted in-process, so the full
start -> provider -> callback flow is exercised without any network or
real provider.

Test driver surface:

* ``issue_code(claims)`` registers an authorization code the token
  endpoint will redeem for an id_token carrying exactly ``claims``.
* ``standard_claims(...)`` builds a passing claim set (iss/aud/sub/
  iat/exp) that individual tests override to produce skew.
* ``token_requests`` records every parsed token-endpoint form body so
  tests can assert on redirect_uri / client authentication.

The module name carries the ``_test_helpers`` suffix so pytest collects
nothing from it.
"""

from __future__ import annotations

import http.server
import secrets
import threading
import time
import urllib.parse
from typing import Any, Dict, List, Optional

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from yoke_core.domain import json_helper


class StubOidcProvider:
    def __init__(
        self,
        *,
        client_id: str = "door-client",
        client_secret: str = "door-client-secret-value-0123456789abcdef",
        declared_issuer_override: Optional[str] = None,
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.kid = "stub-signing-key-1"
        self.declared_issuer_override = declared_issuer_override
        self._private_key = rsa.generate_private_key(
            public_exponent=65537, key_size=2048,
        )
        self._codes: Dict[str, Dict[str, Any]] = {}
        self.token_requests: List[Dict[str, str]] = []

        provider = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:  # keep test output clean
                return

            def _send_json(self, payload: Any, status: int = 200) -> None:
                body = json_helper.dumps_compact(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:
                if self.path == "/.well-known/openid-configuration":
                    self._send_json(provider.discovery_document())
                elif self.path == "/jwks":
                    self._send_json(provider.jwks_document())
                else:
                    self._send_json({"error": "not_found"}, 404)

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                form = dict(
                    urllib.parse.parse_qsl(self.rfile.read(length).decode("utf-8"))
                )
                if self.path != "/token":
                    self._send_json({"error": "not_found"}, 404)
                    return
                provider.token_requests.append(form)
                if form.get("client_secret") != provider.client_secret:
                    self._send_json({"error": "invalid_client"}, 401)
                    return
                claims = provider._codes.pop(str(form.get("code") or ""), None)
                if claims is None:
                    self._send_json({"error": "invalid_grant"}, 400)
                    return
                self._send_json(
                    {
                        "access_token": "stub-access-token",
                        "token_type": "Bearer",
                        "id_token": provider.sign(claims),
                    }
                )

        self._server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever, daemon=True,
        )
        self._thread.start()

    @property
    def issuer(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}"

    def discovery_document(self) -> Dict[str, str]:
        declared = self.declared_issuer_override or self.issuer
        return {
            "issuer": declared,
            "authorization_endpoint": self.issuer + "/authorize",
            "token_endpoint": self.issuer + "/token",
            "jwks_uri": self.issuer + "/jwks",
        }

    def jwks_document(self) -> Dict[str, Any]:
        jwk = jwt.algorithms.RSAAlgorithm.to_jwk(
            self._private_key.public_key(), as_dict=True,
        )
        jwk.update({"kid": self.kid, "use": "sig", "alg": "RS256"})
        return {"keys": [jwk]}

    def sign(self, claims: Dict[str, Any]) -> str:
        return jwt.encode(
            claims, self._private_key, algorithm="RS256",
            headers={"kid": self.kid},
        )

    def sign_symmetric(self, claims: Dict[str, Any]) -> str:
        """An HS256 token signed with the shared client secret — must
        never satisfy JWKS-based verification (algorithm confusion)."""
        return jwt.encode(
            claims, self.client_secret, algorithm="HS256",
            headers={"kid": self.kid},
        )

    def standard_claims(
        self,
        *,
        sub: str = "stub-subject",
        nonce: str = "",
        **overrides: Any,
    ) -> Dict[str, Any]:
        now = int(time.time())
        claims: Dict[str, Any] = {
            "iss": self.issuer,
            "aud": self.client_id,
            "sub": sub,
            "iat": now,
            "exp": now + 300,
        }
        if nonce:
            claims["nonce"] = nonce
        claims.update(overrides)
        return claims

    def issue_code(self, claims: Dict[str, Any]) -> str:
        code = secrets.token_urlsafe(12)
        self._codes[code] = dict(claims)
        return code

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()


__all__ = ["StubOidcProvider"]
