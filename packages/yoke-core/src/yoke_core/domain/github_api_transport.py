"""Redirect-safe HTTP opening for GitHub bearer-token requests."""

from __future__ import annotations

from typing import Any, Callable
import urllib.request

from yoke_contracts.github_origin import (
    GitHubApiEndpoint,
    require_same_github_origin,
)

from yoke_core.domain.gh_rest_transport_test_guard import block_live_test_call


class _ExactOriginRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, endpoint: GitHubApiEndpoint) -> None:
        super().__init__()
        self._endpoint = endpoint

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        require_same_github_origin(newurl, self._endpoint)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class _RejectRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        del req, fp, code, msg, headers, newurl
        return None


def open_same_origin(
    request: urllib.request.Request,
    *,
    endpoint: GitHubApiEndpoint,
    timeout_seconds: float,
    opener: Callable[..., Any] | None = None,
    reject_redirects: bool = False,
) -> Any:
    """Open ``request`` while refusing cross-origin redirects."""
    require_same_github_origin(request.full_url, endpoint)
    if opener is not None:
        response = opener(request, timeout=timeout_seconds)
        final_url = getattr(response, "geturl", lambda: request.full_url)()
        require_same_github_origin(str(final_url), endpoint)
        return response
    block_live_test_call(urllib.request.urlopen, urllib.request.urlopen)
    redirect_handler = (
        _RejectRedirectHandler()
        if reject_redirects
        else _ExactOriginRedirectHandler(endpoint)
    )
    safe_opener = urllib.request.build_opener(redirect_handler)
    return safe_opener.open(request, timeout=timeout_seconds)


__all__ = ["open_same_origin"]
