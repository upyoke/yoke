"""Bounded transport for GitHub App installation-token exchanges."""

from __future__ import annotations

import json
from typing import Any, Callable, Mapping
import urllib.error
import urllib.request

from yoke_contracts import github_app_tokens as token_contract
from yoke_contracts.github_origin import GitHubApiEndpoint, GitHubApiOriginError

from yoke_core.domain import gh_rest_transport
from yoke_core.domain.github_api_transport import open_same_origin
from yoke_core.domain.github_app_token_models import (
    GitHubAppTokenError,
    GitHubAppTokenResponseDecodeError,
    GitHubAppTokenResponseError,
    GitHubAppTokenResponseSizeError,
)
from yoke_core.domain.github_response_safety import (
    GITHUB_SMALL_RESPONSE_LIMIT_BYTES,
    GitHubResponseDecodeError,
    GitHubResponseTooLargeError,
    decode_utf8_response,
    read_bounded_response,
    redact_exact_secrets,
)


def issue_installation_token_request(
    *,
    endpoint: GitHubApiEndpoint,
    installation_id: int,
    app_jwt: str,
    body: Mapping[str, Any],
    opener: Callable[..., Any] | None,
    timeout_seconds: float,
) -> dict[str, Any]:
    """POST one installation-token request within a small JSON envelope."""
    selected_url = (
        f"{endpoint.base_url}/app/installations/{installation_id}/access_tokens"
    )
    request = urllib.request.Request(
        selected_url,
        data=json.dumps(dict(body)).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {app_jwt}",
            "Accept": token_contract.GITHUB_APP_ACCEPT,
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": gh_rest_transport.GITHUB_API_VERSION,
            "User-Agent": token_contract.GITHUB_APP_USER_AGENT,
        },
        method="POST",
    )
    try:
        with open_same_origin(
            request,
            endpoint=endpoint,
            timeout_seconds=timeout_seconds,
            opener=opener,
        ) as response:
            raw = read_bounded_response(
                response,
                limit_bytes=GITHUB_SMALL_RESPONSE_LIMIT_BYTES,
                label="GitHub installation token response",
                check_content_length=True,
            )
    except urllib.error.HTTPError as exc:
        body_text = _read_error_body(exc, secret=app_jwt)
        raise GitHubAppTokenResponseError(
            "GitHub installation token request failed",
            status=exc.code,
            body=body_text,
        ) from None
    except urllib.error.URLError:
        raise GitHubAppTokenError(
            "GitHub installation token request was unavailable"
        ) from None
    except (TimeoutError, OSError):
        raise GitHubAppTokenError(
            "GitHub installation token request was unavailable"
        ) from None
    except GitHubResponseTooLargeError as exc:
        raise GitHubAppTokenResponseSizeError(str(exc)) from None
    except GitHubApiOriginError as exc:
        raise GitHubAppTokenError(redact_exact_secrets(str(exc), (app_jwt,))) from None
    except Exception:
        raise GitHubAppTokenError(
            "GitHub installation token response could not be read"
        ) from None
    try:
        text = decode_utf8_response(raw, label="GitHub installation token response")
    except GitHubResponseDecodeError as exc:
        raise GitHubAppTokenResponseDecodeError(str(exc)) from None
    if app_jwt in text:
        raise GitHubAppTokenResponseDecodeError(
            "GitHub installation token response echoed the request credential"
        )
    text = redact_exact_secrets(text, (app_jwt,))
    try:
        payload = json.loads(text or "{}")
    except ValueError:
        raise GitHubAppTokenResponseDecodeError(
            "GitHub installation token response was not valid JSON"
        ) from None
    if not isinstance(payload, dict):
        raise GitHubAppTokenResponseDecodeError(
            "GitHub installation token response must be a JSON object"
        )
    return payload


def _read_error_body(exc: urllib.error.HTTPError, *, secret: str) -> str:
    try:
        raw = read_bounded_response(
            exc,
            limit_bytes=GITHUB_SMALL_RESPONSE_LIMIT_BYTES,
            label="GitHub installation token error response",
        )
        text = decode_utf8_response(
            raw, label="GitHub installation token error response"
        )
    except GitHubResponseTooLargeError:
        text = "GitHub installation token error response exceeded the size limit"
    except GitHubResponseDecodeError:
        text = "GitHub installation token error response was not valid UTF-8"
    except Exception:
        text = "GitHub installation token error response could not be read"
    return redact_exact_secrets(text, (secret,))


__all__ = ["issue_installation_token_request"]
