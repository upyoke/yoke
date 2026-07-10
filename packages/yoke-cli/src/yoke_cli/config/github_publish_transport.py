"""Redirect-safe GitHub REST transport for local publish operations."""

from __future__ import annotations

import json
from typing import Any, Mapping
import urllib.error
import urllib.parse
import urllib.request

from yoke_contracts import github_app_tokens, github_origin

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
) -> Any:
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
        with _urlopen(request, timeout=_TIMEOUT_S) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = _error_detail(exc)
        raise GitHubPublishError(
            f"GitHub call failed: {method} {url} returned HTTP {exc.code}"
            + (f" — {detail}" if detail else ""), status=exc.code,
        ) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise GitHubPublishError(f"GitHub call failed against {url}: {exc}") from exc
    try:
        return json.loads(raw) if raw else None
    except ValueError as exc:
        raise GitHubPublishError(
            f"GitHub call returned invalid JSON from {url}"
        ) from exc


def _error_detail(exc: urllib.error.HTTPError) -> str:
    try:
        payload = json.loads(exc.read().decode("utf-8"))
    except (ValueError, OSError):
        return ""
    if isinstance(payload, Mapping) and payload.get("message"):
        return str(payload["message"])
    return ""


__all__ = ["GitHubPublishError", "request_json"]
