"""Read-only GitHub App user APIs for local installation discovery."""

from __future__ import annotations

import json
import time
from typing import Any, Callable, Mapping
import urllib.error
import urllib.parse
import urllib.request

from yoke_contracts import (
    github_app_snapshot,
    github_app_tokens,
    github_origin,
)
from yoke_cli.config.github_app_user_api_models import (
    GitHubAppUserApiError,
    normalize_installation,
    normalize_repository,
    required_int,
    required_string,
)
from yoke_cli.config.github_discovery_budget import (
    DISCOVERY_DEADLINE_SECONDS,
    DiscoveryBudget,
)
from yoke_cli.config import github_response_safety

MAX_PAGINATION_PAGES = 100


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_urlopen = urllib.request.build_opener(_NoRedirectHandler()).open


def discover_access(
    *,
    api_url: str,
    access_token: str,
    opener: Callable[..., Any] | None = None,
    timeout_seconds: float = 30.0,
    total_deadline_seconds: float = DISCOVERY_DEADLINE_SECONDS,
    monotonic: Callable[[], float] = time.monotonic,
    web_url: str | None = None,
) -> dict[str, Any]:
    """Return the signed-in user, App installations, and visible repos."""
    base = validated_api_url(api_url)
    web_endpoint = None
    if web_url is not None:
        try:
            web_endpoint = github_origin.validate_github_endpoint_pair(
                base,
                web_url,
            ).web
        except github_origin.GitHubApiOriginError as exc:
            raise GitHubAppUserApiError(str(exc)) from exc
    token = required_string(access_token, "access_token")
    budget = DiscoveryBudget(
        deadline=monotonic() + total_deadline_seconds,
        monotonic=monotonic,
        error_type=GitHubAppUserApiError,
    )
    user = _request_json(
        f"{base}/user",
        token=token,
        opener=opener,
        timeout_seconds=timeout_seconds,
        budget=budget,
    )
    installations = _paginate(
        f"{base}/user/installations",
        collection_key="installations",
        token=token,
        opener=opener,
        timeout_seconds=timeout_seconds,
        budget=budget,
    )
    normalized_installations = [
        normalize_installation(item, web_endpoint=web_endpoint)
        for item in installations
        if isinstance(item, Mapping)
    ]
    repositories: list[dict[str, Any]] = []
    for installation in normalized_installations:
        if installation["suspended"]:
            continue
        installation_id = installation["installation_id"]
        rows = _paginate(
            f"{base}/user/installations/{installation_id}/repositories",
            collection_key="repositories",
            token=token,
            opener=opener,
            timeout_seconds=timeout_seconds,
            budget=budget,
        )
        repositories.extend(
            normalize_repository(item, installation_id=installation_id)
            for item in rows
            if isinstance(item, Mapping)
        )
    try:
        login = github_app_snapshot.user_login(user.get("login"))
    except github_app_snapshot.GitHubAppSnapshotError as exc:
        raise GitHubAppUserApiError(str(exc)) from exc
    return {
        "user": {"id": required_int(user.get("id"), "user.id"), "login": login},
        "installations": normalized_installations,
        "repositories": repositories,
    }


def validated_api_url(value: str) -> str:
    try:
        return github_origin.validate_github_api_endpoint(value).base_url
    except github_origin.GitHubApiOriginError as exc:
        raise GitHubAppUserApiError(str(exc)) from exc


def _paginate(
    url: str,
    *,
    collection_key: str,
    token: str,
    opener: Callable[..., Any] | None,
    timeout_seconds: float,
    budget: DiscoveryBudget,
) -> list[Any]:
    rows: list[Any] = []
    page = 1
    while page <= MAX_PAGINATION_PAGES:
        separator = "&" if "?" in url else "?"
        payload = _request_json(
            f"{url}{separator}per_page=100&page={page}",
            token=token,
            opener=opener,
            timeout_seconds=timeout_seconds,
            budget=budget,
        )
        batch = payload.get(collection_key)
        if not isinstance(batch, list):
            raise GitHubAppUserApiError(
                f"GitHub response {collection_key} must be a list"
            )
        budget.add_rows(len(batch))
        rows.extend(batch)
        if len(batch) < 100:
            return rows
        page += 1
    raise GitHubAppUserApiError(
        f"GitHub {collection_key} listing exceeded {MAX_PAGINATION_PAGES} pages"
    )


def _request_json(
    url: str,
    *,
    token: str,
    opener: Callable[..., Any] | None,
    timeout_seconds: float,
    budget: DiscoveryBudget,
) -> dict[str, Any]:
    endpoint = urllib.parse.urlsplit(url).path or "/"
    request = urllib.request.Request(
        url,
        headers={
            "Accept": github_app_tokens.GITHUB_APP_ACCEPT,
            "Authorization": f"Bearer {token}",
            "User-Agent": github_app_tokens.GITHUB_APP_USER_AGENT,
            "X-GitHub-Api-Version": github_app_tokens.GITHUB_API_VERSION,
        },
        method="GET",
    )
    remaining_seconds = budget.before_request()
    try:
        with (opener or _urlopen)(
            request, timeout=min(timeout_seconds, remaining_seconds)
        ) as response:
            _require_final_url(response, request.full_url)
            raw = github_response_safety.read_bounded(
                response,
                maximum_bytes=github_app_tokens.GITHUB_API_RESPONSE_MAX_BYTES,
                deadline=budget.deadline,
                monotonic=budget.monotonic,
            )
    except urllib.error.HTTPError as exc:
        detail = _http_error_detail(
            exc,
            secret=token,
            deadline=budget.deadline,
            monotonic=budget.monotonic,
        )
        raise GitHubAppUserApiError(
            f"GitHub user API request to {endpoint} failed with HTTP "
            f"{exc.code}{detail}",
            status=exc.code,
        ) from exc
    except urllib.error.URLError as exc:
        raise GitHubAppUserApiError(
            "GitHub user API failed because GitHub could not be reached"
        ) from exc
    except (TimeoutError, OSError) as exc:
        raise GitHubAppUserApiError(
            "GitHub user API failed because GitHub could not be reached"
        ) from exc
    except github_response_safety.GitHubResponseReadError as exc:
        if "too large" in str(exc):
            raise GitHubAppUserApiError(
                "GitHub user API response is too large"
            ) from exc
        raise GitHubAppUserApiError(
            "GitHub access discovery exceeded its operation deadline"
        ) from exc
    budget.add_response(len(raw))
    try:
        payload = json.loads(raw.decode("utf-8") or "{}")
    except (UnicodeDecodeError, ValueError) as exc:
        raise GitHubAppUserApiError("GitHub user API response is not JSON") from exc
    if not isinstance(payload, dict):
        raise GitHubAppUserApiError("GitHub user API response must be an object")
    return payload


def _http_error_detail(
    exc: urllib.error.HTTPError,
    *,
    secret: str,
    deadline: float,
    monotonic: Callable[[], float],
) -> str:
    parts = []
    request_id = github_response_safety.safe_error_text(
        (exc.headers or {}).get("X-GitHub-Request-Id") or "",
        secrets=(secret,),
    )
    if request_id:
        parts.append(f"request_id={request_id[:100]}")
    try:
        raw = github_response_safety.read_bounded(
            exc,
            maximum_bytes=github_app_tokens.GITHUB_API_RESPONSE_MAX_BYTES,
            deadline=deadline,
            monotonic=monotonic,
        )
        payload = (
            json.loads(raw.decode("utf-8") or "{}")
            if len(raw) <= github_app_tokens.GITHUB_API_RESPONSE_MAX_BYTES
            else {}
        )
    except (
        AttributeError,
        OSError,
        UnicodeDecodeError,
        ValueError,
        github_response_safety.GitHubResponseReadError,
    ):
        payload = {}
    if isinstance(payload, Mapping):
        message = github_response_safety.safe_error_text(
            payload.get("message"),
            secrets=(secret,),
        )
        if message:
            parts.append(f"message={message[:200]}")
    return f" ({'; '.join(parts)})" if parts else ""


def _require_final_url(response: Any, expected: str) -> None:
    geturl = getattr(response, "geturl", None)
    actual = str(geturl() if callable(geturl) else "")
    if actual != expected:
        raise GitHubAppUserApiError(
            "GitHub user API response URL changed; redirects are not allowed"
        )


__all__ = [
    "GitHubAppUserApiError",
    "discover_access",
    "validated_api_url",
]
