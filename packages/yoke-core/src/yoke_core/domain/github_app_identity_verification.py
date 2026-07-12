"""Bounded exact-origin authentication of the configured GitHub App."""

from __future__ import annotations

import json
from typing import Any, Callable, Mapping
import urllib.error
import urllib.request

from yoke_contracts import github_app_tokens as token_contract
from yoke_contracts.github_origin import GitHubApiOriginError

from yoke_core.domain import gh_rest_transport
from yoke_core.domain.github_api_transport import open_same_origin
from yoke_core.domain.github_app_control_plane import GitHubAppControlPlaneConfig
from yoke_core.domain.github_app_identity import (
    GitHubAppIdentity,
    GitHubAppIdentityVerificationError,
    validate_identity_payload,
)
from yoke_core.domain.github_app_jwt import generate_app_jwt
from yoke_core.domain.github_app_verification_response import (
    GitHubAppVerificationResponseError,
    read_bounded_verification_response,
    require_unredirected_verification_response,
)


def fetch_authenticated_app_identity(
    config: GitHubAppControlPlaneConfig,
    *,
    opener: Callable[..., Any] | None = None,
    jwt_factory: Callable[..., str] | None = None,
    timeout_seconds: float = 5.0,
) -> GitHubAppIdentity:
    """Sign one App JWT and return the authenticated ``GET /app`` identity."""
    token = (jwt_factory or generate_app_jwt)(
        issuer=config.issuer,
        private_key_pem=config.private_key_pem,
    )
    request = urllib.request.Request(
        config.endpoint.url("/app"),
        method="GET",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": token_contract.GITHUB_APP_ACCEPT,
            "X-GitHub-Api-Version": gh_rest_transport.GITHUB_API_VERSION,
            "User-Agent": token_contract.GITHUB_APP_USER_AGENT,
        },
    )
    try:
        with open_same_origin(
            request,
            endpoint=config.endpoint,
            timeout_seconds=timeout_seconds,
            opener=opener,
            reject_redirects=True,
        ) as response:
            require_unredirected_verification_response(
                response, expected_url=request.full_url
            )
            raw = read_bounded_verification_response(response)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
        raise GitHubAppIdentityVerificationError(
            "GitHub App identity verification was unavailable"
        ) from exc
    except GitHubApiOriginError as exc:
        raise GitHubAppIdentityVerificationError(str(exc)) from exc
    except GitHubAppVerificationResponseError as exc:
        raise GitHubAppIdentityVerificationError(str(exc)) from exc
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise GitHubAppIdentityVerificationError(
            "GitHub App identity response was not valid JSON"
        ) from exc
    if not isinstance(payload, Mapping):
        raise GitHubAppIdentityVerificationError(
            "GitHub App identity response must be an object"
        )
    return validate_identity_payload(config.issuer, dict(payload))


__all__ = ["fetch_authenticated_app_identity"]
