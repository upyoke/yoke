"""Stub provider lifetimes must not leak discovery or signing-key state."""

from __future__ import annotations

from runtime.api import oidc_provider_test_helpers
from runtime.api.oidc_provider_test_helpers import StubOidcProvider
from yoke_core.api import oidc_client
from yoke_core.api.oidc_config import OidcConfig


def _verified_claims(provider: StubOidcProvider) -> dict:
    config = OidcConfig(
        issuer=provider.issuer,
        client_id=provider.client_id,
        client_secret=provider.client_secret,
        redirect_base_url="http://testserver",
        allow_unverified_email=False,
    )
    nonce = "browser-nonce"
    return oidc_client.verify_id_token(
        config,
        oidc_client.discover(provider.issuer),
        id_token=provider.sign(provider.standard_claims(nonce=nonce)),
        nonce=nonce,
    )


def test_recycled_provider_address_uses_its_own_signing_key(monkeypatch):
    server_type = oidc_provider_test_helpers.http.server.ThreadingHTTPServer
    monkeypatch.setattr(server_type, "allow_reuse_address", True)
    first = StubOidcProvider()
    try:
        assert _verified_claims(first)["iss"] == first.issuer
        address = first._server.server_address
        issuer = first.issuer
    finally:
        first.close()

    def recycled_server(_address, handler):
        return server_type(address, handler)

    monkeypatch.setattr(
        oidc_provider_test_helpers.http.server,
        "ThreadingHTTPServer",
        recycled_server,
    )
    second = StubOidcProvider()
    try:
        assert second.issuer == issuer
        assert _verified_claims(second)["iss"] == second.issuer
    finally:
        second.close()


def test_closing_provider_releases_only_its_own_cached_state():
    first = StubOidcProvider()
    second = StubOidcProvider()
    try:
        _verified_claims(first)
        _verified_claims(second)
        second_endpoints = oidc_client.discover(second.issuer)
        second_keys = oidc_client._JWKS_CLIENT_CACHE[second_endpoints.jwks_uri]
        first.close()

        assert first.issuer not in oidc_client._DISCOVERY_CACHE
        assert first.issuer + "/jwks" not in oidc_client._JWKS_CLIENT_CACHE
        assert oidc_client.discover(second.issuer) is second_endpoints
        assert oidc_client._JWKS_CLIENT_CACHE[second_endpoints.jwks_uri] is second_keys
        assert _verified_claims(second)["iss"] == second.issuer
    finally:
        first.close()
        second.close()
