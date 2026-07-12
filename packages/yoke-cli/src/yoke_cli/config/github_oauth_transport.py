"""Bounded, redirect-denied GitHub OAuth form transport."""

from __future__ import annotations

import json
import time
from typing import Any, Callable, Mapping
import urllib.error
import urllib.parse
import urllib.request

if __package__:
    from yoke_contracts import github_app_tokens as token_contract
    from yoke_cli.config import github_response_safety
else:  # pragma: no cover - copied helper always uses its immutable siblings
    import _yoke_github_app_tokens as token_contract  # type: ignore
    import _yoke_github_response_safety as github_response_safety  # type: ignore


class GitHubOAuthTransportError(RuntimeError):
    """A GitHub OAuth response could not be obtained or trusted."""


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_urlopen = urllib.request.build_opener(_NoRedirectHandler()).open


def post_form(
    url: str,
    params: Mapping[str, str],
    *,
    opener: Callable[..., Any] | None,
    timeout_seconds: float,
    monotonic: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """POST one bounded form without following redirects."""

    request = urllib.request.Request(
        url,
        data=urllib.parse.urlencode(params).encode("utf-8"),
        headers={
            "Accept": token_contract.GITHUB_JSON_ACCEPT,
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": token_contract.GITHUB_APP_USER_AGENT,
        },
        method="POST",
    )
    try:
        deadline = monotonic() + timeout_seconds
        with (opener or _urlopen)(request, timeout=timeout_seconds) as response:
            _require_final_url(response, request.full_url)
            raw = github_response_safety.read_bounded(
                response,
                maximum_bytes=token_contract.GITHUB_OAUTH_RESPONSE_MAX_BYTES,
                deadline=deadline,
                monotonic=monotonic,
            )
    except urllib.error.HTTPError as exc:
        raise GitHubOAuthTransportError(
            f"GitHub App user-token refresh failed with HTTP {exc.code}"
        ) from exc
    except urllib.error.URLError as exc:
        raise GitHubOAuthTransportError(
            "GitHub App user-token refresh failed because GitHub could not be reached"
        ) from exc
    except (TimeoutError, OSError) as exc:
        raise GitHubOAuthTransportError(
            "GitHub App user-token refresh failed because GitHub could not be reached"
        ) from exc
    except github_response_safety.GitHubResponseReadError as exc:
        if "too large" in str(exc):
            raise GitHubOAuthTransportError(
                "GitHub App user-token response is too large"
            ) from exc
        raise GitHubOAuthTransportError(
            "GitHub App user-token refresh exceeded its operation deadline"
        ) from exc
    try:
        payload = json.loads(raw.decode("utf-8") or "{}")
    except (UnicodeDecodeError, ValueError) as exc:
        raise GitHubOAuthTransportError(
            "GitHub App user-token response is not JSON"
        ) from exc
    if not isinstance(payload, dict):
        raise GitHubOAuthTransportError(
            "GitHub App user-token response must be an object"
        )
    return payload


def _require_final_url(response: Any, expected: str) -> None:
    geturl = getattr(response, "geturl", None)
    actual = str(geturl() if callable(geturl) else "")
    if actual != expected:
        raise GitHubOAuthTransportError(
            "GitHub App user-token response URL changed; redirects are not allowed"
        )


__all__ = ["GitHubOAuthTransportError", "post_form"]
