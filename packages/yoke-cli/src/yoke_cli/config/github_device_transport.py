"""Bounded form transport for GitHub Device Flow endpoints."""

from __future__ import annotations

import json
from typing import Any, Callable, Mapping
import urllib.error
import urllib.parse
import urllib.request

from yoke_cli.config import github_response_safety
from yoke_contracts import github_app_tokens as token_contract


def post_form(
    url: str,
    values: Mapping[str, str],
    *,
    opener: Callable[..., Any],
    timeout_seconds: float,
    deadline: float,
    monotonic: Callable[[], float],
    error_type: type[RuntimeError],
) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=urllib.parse.urlencode(values).encode("utf-8"),
        headers={
            "Accept": token_contract.GITHUB_JSON_ACCEPT,
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": token_contract.GITHUB_APP_USER_AGENT,
        },
        method="POST",
    )
    try:
        with opener(request, timeout=timeout_seconds) as response:
            _require_final_url(response, request.full_url, error_type=error_type)
            raw = github_response_safety.read_bounded(
                response,
                maximum_bytes=token_contract.GITHUB_OAUTH_RESPONSE_MAX_BYTES,
                deadline=deadline,
                monotonic=monotonic,
            )
    except urllib.error.HTTPError as exc:
        raise error_type(
            f"GitHub device authorization failed with HTTP {exc.code}"
        ) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise error_type(
            "GitHub device authorization failed because GitHub could not be reached"
        ) from exc
    except github_response_safety.GitHubResponseReadError as exc:
        if "too large" in str(exc):
            raise error_type(
                "GitHub device authorization response is too large"
            ) from exc
        raise error_type(
            "GitHub device authorization expired while waiting for GitHub"
        ) from exc
    try:
        payload = json.loads(raw.decode("utf-8") or "{}")
    except (UnicodeDecodeError, ValueError) as exc:
        raise error_type(
            "GitHub device authorization response is not JSON"
        ) from exc
    if not isinstance(payload, dict):
        raise error_type(
            "GitHub device authorization response must be an object"
        )
    return payload


def _require_final_url(
    response: Any,
    expected: str,
    *,
    error_type: type[RuntimeError],
) -> None:
    geturl = getattr(response, "geturl", None)
    actual = str(geturl() if callable(geturl) else "")
    if actual != expected:
        raise error_type(
            "GitHub device authorization response URL changed; redirects are not allowed"
        )


__all__ = ["post_form"]
