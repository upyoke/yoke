"""Bounded exact-origin GitHub user-authorization reads."""

from __future__ import annotations

import json
from typing import Any, Callable, Mapping
import urllib.error
import urllib.parse
import urllib.request

from yoke_contracts import github_app_tokens as token_contract
from yoke_contracts.github_origin import GitHubApiEndpoint, GitHubApiOriginError

from yoke_core.domain import gh_rest_transport
from yoke_core.domain.github_api_transport import open_same_origin
from yoke_core.domain.github_app_verification_response import (
    GITHUB_APP_COLLECTION_RESPONSE_LIMIT_BYTES,
    GITHUB_APP_VERIFICATION_RESPONSE_LIMIT_BYTES,
    GitHubAppVerificationResponseError,
    read_bounded_verification_response,
    require_unredirected_verification_response,
)


class GitHubUserVerificationError(ValueError):
    """A user token cannot prove the requested binding intent."""


def _find_paginated(
    endpoint: GitHubApiEndpoint,
    path: str,
    *,
    collection_key: str,
    selected_id: int,
    token: str,
    opener: Callable[..., Any] | None,
    timeout_seconds: float,
) -> Mapping[str, Any] | None:
    per_page = 100
    for page in range(1, 101):
        query = urllib.parse.urlencode({"per_page": per_page, "page": page})
        payload = _get_json(
            endpoint,
            f"{path}?{query}",
            token=token,
            opener=opener,
            timeout_seconds=timeout_seconds,
            response_limit_bytes=GITHUB_APP_COLLECTION_RESPONSE_LIMIT_BYTES,
        )
        raw_items = payload.get(collection_key)
        if not isinstance(raw_items, list):
            raise GitHubUserVerificationError(
                f"GitHub response omitted {collection_key}"
            )
        items = [item for item in raw_items if isinstance(item, Mapping)]
        for item in items:
            try:
                item_id = int(item.get("id"))
            except (TypeError, ValueError):
                continue
            if item_id == selected_id:
                return item
        if len(raw_items) < per_page:
            return None
    raise GitHubUserVerificationError(
        f"GitHub {collection_key} listing exceeded the pagination safety limit"
    )


def _get_json(
    endpoint: GitHubApiEndpoint,
    path: str,
    *,
    token: str,
    opener: Callable[..., Any] | None,
    timeout_seconds: float,
    response_limit_bytes: int = GITHUB_APP_VERIFICATION_RESPONSE_LIMIT_BYTES,
) -> dict[str, Any]:
    request = urllib.request.Request(
        endpoint.url(path),
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": token_contract.GITHUB_APP_ACCEPT,
            "X-GitHub-Api-Version": gh_rest_transport.GITHUB_API_VERSION,
            "User-Agent": token_contract.GITHUB_APP_USER_AGENT,
        },
        method="GET",
    )
    try:
        with open_same_origin(
            request,
            endpoint=endpoint,
            timeout_seconds=timeout_seconds,
            opener=opener,
            reject_redirects=True,
        ) as response:
            require_unredirected_verification_response(
                response, expected_url=request.full_url
            )
            raw = read_bounded_verification_response(
                response,
                limit_bytes=response_limit_bytes,
            )
    except urllib.error.HTTPError as exc:
        raise GitHubUserVerificationError(
            f"GitHub user authorization verification failed with HTTP {exc.code}"
        ) from exc
    except urllib.error.URLError as exc:
        raise GitHubUserVerificationError(
            f"GitHub user authorization verification failed: {exc.reason}"
        ) from exc
    except TimeoutError as exc:
        raise GitHubUserVerificationError(
            "GitHub user authorization verification timed out"
        ) from exc
    except GitHubApiOriginError as exc:
        raise GitHubUserVerificationError(str(exc)) from exc
    except GitHubAppVerificationResponseError as exc:
        raise GitHubUserVerificationError(str(exc)) from exc
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise GitHubUserVerificationError(
            "GitHub user authorization response was not valid JSON"
        ) from exc
    if not isinstance(parsed, dict):
        raise GitHubUserVerificationError(
            "GitHub user authorization response must be a JSON object"
        )
    return parsed


__all__ = ["GitHubUserVerificationError"]
