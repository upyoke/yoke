"""Redirect-safe GitHub REST transport for local publish operations."""

from __future__ import annotations

import json
import time
from typing import Any, Callable, Mapping
import urllib.error
import urllib.parse
import urllib.request

from yoke_contracts import github_app_tokens, github_origin
from yoke_cli.config import github_response_safety

_TIMEOUT_S = 20.0


class GitHubPublishError(RuntimeError):
    """A GitHub publish REST call failed, optionally with HTTP ``status``."""

    def __init__(self, *args: Any, status: int | None = None) -> None:
        super().__init__(*args)
        self.status = status


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_urlopen = urllib.request.build_opener(_NoRedirectHandler()).open


def request_json(
    api_url: str,
    path: str,
    token: str,
    *,
    method: str = "GET",
    query: Mapping[str, str] | None = None,
    body: Mapping[str, Any] | None = None,
    deadline: float | None = None,
    monotonic: Callable[[], float] | None = None,
) -> Any:
    clock = monotonic or time.monotonic
    selected_deadline = deadline or (clock() + _TIMEOUT_S)
    try:
        endpoint = github_origin.validate_github_api_endpoint(api_url)
    except github_origin.GitHubApiOriginError as exc:
        raise GitHubPublishError(str(exc)) from exc
    url = endpoint.url(path)
    if query:
        url = url + "?" + urllib.parse.urlencode(query)
    data = json.dumps(dict(body)).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        url, data=data, method=method,
        headers={
            "Accept": github_app_tokens.GITHUB_APP_ACCEPT,
            "Authorization": f"Bearer {token}",
            "User-Agent": github_app_tokens.GITHUB_APP_USER_AGENT,
            "X-GitHub-Api-Version": github_app_tokens.GITHUB_API_VERSION,
            "Content-Type": "application/json",
        },
    )
    try:
        remaining = selected_deadline - clock()
        if remaining <= 0:
            raise github_response_safety.GitHubResponseReadError(
                "GitHub response exceeded its deadline"
            )
        with _urlopen(request, timeout=min(_TIMEOUT_S, remaining)) as response:
            response_body = github_response_safety.read_bounded(
                response,
                maximum_bytes=github_app_tokens.GITHUB_API_RESPONSE_MAX_BYTES,
                deadline=selected_deadline,
                monotonic=clock,
            )
    except urllib.error.HTTPError as exc:
        detail = _error_detail(
            exc, secret=token, deadline=selected_deadline,
            monotonic=clock,
        )
        raise GitHubPublishError(
            f"GitHub call failed: {method} {url} returned HTTP {exc.code}"
            + (f" — {detail}" if detail else ""), status=exc.code,
        ) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise GitHubPublishError(
            f"GitHub call failed against {url} because GitHub could not be reached"
        ) from exc
    except github_response_safety.GitHubResponseReadError as exc:
        if "too large" in str(exc):
            raise GitHubPublishError(
                f"GitHub call returned an oversized response from {url}"
            ) from exc
        raise GitHubPublishError(
            f"GitHub call exceeded its operation deadline against {url}"
        ) from exc
    try:
        raw = response_body.decode("utf-8")
        return json.loads(raw) if raw else None
    except (UnicodeDecodeError, ValueError) as exc:
        raise GitHubPublishError(
            f"GitHub call returned invalid JSON from {url}"
        ) from exc


def _error_detail(
    exc: urllib.error.HTTPError,
    *,
    secret: str,
    deadline: float,
    monotonic: Callable[[], float],
) -> str:
    try:
        raw = github_response_safety.read_bounded(
            exc,
            maximum_bytes=github_app_tokens.GITHUB_API_RESPONSE_MAX_BYTES,
            deadline=deadline,
            monotonic=monotonic,
        )
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, OSError, github_response_safety.GitHubResponseReadError):
        return ""
    if isinstance(payload, Mapping) and payload.get("message"):
        return github_response_safety.safe_error_text(
            payload["message"], secrets=(secret,)
        )
    return ""


__all__ = ["GitHubPublishError", "request_json"]
