"""OIDC relying-party client for the browser sign-in door.

Provider interaction for one operator-configured OpenID Connect
provider (config resolution lives in :mod:`yoke_core.api.oidc_config`;
the state/nonce record in :mod:`yoke_core.api.oidc_flow_state`):

* **Discovery** (:func:`discover`) — ``GET {issuer}/.well-known/
  openid-configuration`` via stdlib urllib, cached per process.
* **Code exchange** (:func:`exchange_code`) — authorization-code grant
  against the discovered token endpoint (``client_secret_post`` client
  authentication: id + secret ride the form body, which every major
  provider accepts).
* **id_token verification** (:func:`verify_id_token`) — signature via
  PyJWT's ``PyJWKClient`` against the provider JWKS (cached per
  process), with issuer, audience (= client id), expiry, and nonce all
  enforced. Only asymmetric algorithms are accepted — an HS* token
  signed with the shared client secret is rejected structurally.

No secret material is ever logged or embedded in error messages raised
from this module.
"""

from __future__ import annotations

import hmac
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

import jwt

from yoke_core.api.oidc_config import (
    OIDC_ISSUER_ENV,
    OidcConfig,
    OidcError,
    callback_url,
)
from yoke_core.api.oidc_flow_state import FlowState
from yoke_core.domain import json_helper


#: Scopes requested from the provider: identity plus the email claim the
#: sign-in resolution ladder matches invites and auto-join against.
OIDC_SCOPE = "openid email profile"

#: One deadline for every provider round-trip (discovery, JWKS, token).
HTTP_TIMEOUT_S = 10

#: Asymmetric signature algorithms accepted on id_tokens. HS* is
#: deliberately absent: a symmetric token signed with the shared client
#: secret must never satisfy JWKS-based verification (algorithm
#: confusion hardening).
ALLOWED_SIGNING_ALGORITHMS = (
    "RS256", "RS384", "RS512", "ES256", "ES384", "ES512", "PS256",
)


class OidcDiscoveryError(OidcError):
    """The provider discovery document could not be fetched or is invalid."""


class OidcExchangeError(OidcError):
    """The authorization-code exchange against the token endpoint failed."""


class OidcVerificationError(OidcError):
    """The id_token failed signature or claim verification."""


@dataclass(frozen=True)
class ProviderEndpoints:
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str


# Per-process caches; provider metadata is stable for a process lifetime.
_DISCOVERY_CACHE: dict[str, ProviderEndpoints] = {}
_JWKS_CLIENT_CACHE: dict[str, "jwt.PyJWKClient"] = {}


def _http_get_json(url: str) -> Any:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_S) as response:
        body = response.read().decode("utf-8")
    return json_helper.loads_text(body)


def discover(issuer: str) -> ProviderEndpoints:
    """Fetch (or return the cached) provider discovery document."""
    cached = _DISCOVERY_CACHE.get(issuer)
    if cached is not None:
        return cached
    url = issuer.rstrip("/") + "/.well-known/openid-configuration"
    try:
        document = _http_get_json(url)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise OidcDiscoveryError(
            f"could not fetch the provider discovery document from {url}: "
            f"{exc.__class__.__name__}"
        ) from exc
    if not isinstance(document, dict):
        raise OidcDiscoveryError(
            "the provider discovery document is not a JSON object"
        )
    missing = [
        key
        for key in ("issuer", "authorization_endpoint", "token_endpoint", "jwks_uri")
        if not str(document.get(key) or "").strip()
    ]
    if missing:
        raise OidcDiscoveryError(
            "the provider discovery document is missing: " + ", ".join(missing)
        )
    declared_issuer = str(document["issuer"]).rstrip("/")
    if declared_issuer != issuer.rstrip("/"):
        raise OidcDiscoveryError(
            f"the provider discovery document declares issuer "
            f"{document['issuer']!r}, which does not match the configured "
            f"{OIDC_ISSUER_ENV}"
        )
    endpoints = ProviderEndpoints(
        issuer=str(document["issuer"]),
        authorization_endpoint=str(document["authorization_endpoint"]),
        token_endpoint=str(document["token_endpoint"]),
        jwks_uri=str(document["jwks_uri"]),
    )
    _DISCOVERY_CACHE[issuer] = endpoints
    return endpoints


def _jwks_client(jwks_uri: str) -> "jwt.PyJWKClient":
    client = _JWKS_CLIENT_CACHE.get(jwks_uri)
    if client is None:
        client = jwt.PyJWKClient(jwks_uri, timeout=HTTP_TIMEOUT_S)
        _JWKS_CLIENT_CACHE[jwks_uri] = client
    return client


def authorization_request_url(
    config: OidcConfig,
    endpoints: ProviderEndpoints,
    flow: FlowState,
) -> str:
    """Build the provider authorization-endpoint redirect target."""
    query = urllib.parse.urlencode(
        {
            "response_type": "code",
            "client_id": config.client_id,
            "redirect_uri": callback_url(config),
            "scope": OIDC_SCOPE,
            "state": flow.state,
            "nonce": flow.nonce,
        }
    )
    separator = "&" if "?" in endpoints.authorization_endpoint else "?"
    return endpoints.authorization_endpoint + separator + query


def exchange_code(
    config: OidcConfig,
    endpoints: ProviderEndpoints,
    *,
    code: str,
) -> dict:
    """Redeem the authorization code for the provider token response."""
    form = urllib.parse.urlencode(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": callback_url(config),
            "client_id": config.client_id,
            "client_secret": config.client_secret,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        endpoints.token_endpoint,
        data=form,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_S) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        # The provider's error status is operator-diagnostic; the body may
        # echo request parameters (which include the client secret), so it
        # never rides the raised message.
        raise OidcExchangeError(
            f"the token endpoint answered HTTP {exc.code}"
        ) from exc
    except (urllib.error.URLError, OSError) as exc:
        raise OidcExchangeError(
            f"the token endpoint was unreachable: {exc.__class__.__name__}"
        ) from exc
    try:
        payload = json_helper.loads_text(body)
    except ValueError as exc:
        raise OidcExchangeError(
            "the token endpoint answered non-JSON content"
        ) from exc
    if not isinstance(payload, dict) or not str(payload.get("id_token") or ""):
        raise OidcExchangeError(
            "the token endpoint response carries no id_token"
        )
    return payload


def verify_id_token(
    config: OidcConfig,
    endpoints: ProviderEndpoints,
    *,
    id_token: str,
    nonce: str,
) -> dict:
    """Verify signature, issuer, audience, expiry, and nonce; return claims."""
    try:
        signing_key = _jwks_client(endpoints.jwks_uri).get_signing_key_from_jwt(
            id_token
        )
        claims = jwt.decode(
            id_token,
            signing_key.key,
            algorithms=list(ALLOWED_SIGNING_ALGORITHMS),
            audience=config.client_id,
            issuer=endpoints.issuer,
            options={"require": ["exp", "iss", "aud", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise OidcVerificationError(
            f"id_token verification failed: {exc.__class__.__name__}"
        ) from exc
    token_nonce = str(claims.get("nonce") or "")
    if not token_nonce or not hmac.compare_digest(token_nonce, nonce):
        raise OidcVerificationError(
            "id_token verification failed: nonce mismatch"
        )
    return claims


__all__ = [
    "ALLOWED_SIGNING_ALGORITHMS",
    "HTTP_TIMEOUT_S",
    "OIDC_SCOPE",
    "OidcDiscoveryError",
    "OidcExchangeError",
    "OidcVerificationError",
    "ProviderEndpoints",
    "authorization_request_url",
    "discover",
    "exchange_code",
    "verify_id_token",
]
