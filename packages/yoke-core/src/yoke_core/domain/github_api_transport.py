"""Redirect-safe HTTP opening for GitHub bearer-token requests."""

from __future__ import annotations

from typing import Any, Callable
import urllib.request

from yoke_cli.transport import response_deadline_read
from yoke_cli.transport.response_deadline_open import (
    ResponseOpenDeadlineError,
    open_https_caller_owned,
    open_replay_safe,
)
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


def open_same_origin_deadline(
    request: urllib.request.Request,
    *,
    endpoint: GitHubApiEndpoint,
    deadline: float,
    replay_safe: bool,
    opener: Callable[..., Any] | None = None,
    reject_redirects: bool = False,
    clock: Callable[[], float] | None = None,
) -> Any:
    """Open one GitHub request under its whole-operation deadline."""
    selected_clock = clock or response_deadline_read.monotonic
    require_same_github_origin(request.full_url, endpoint)

    if opener is not None:
        if replay_safe:
            return open_replay_safe(
                request,
                opener=lambda selected, timeout: open_same_origin(
                    selected,
                    endpoint=endpoint,
                    timeout_seconds=timeout,
                    opener=opener,
                    reject_redirects=reject_redirects,
                ),
                deadline=deadline,
                clock=selected_clock,
            )
        remaining = deadline - selected_clock()
        if remaining <= 0:
            raise ResponseOpenDeadlineError(
                "GitHub request open exceeded the time limit"
            )
        response = open_same_origin(
            request,
            endpoint=endpoint,
            timeout_seconds=remaining,
            opener=opener,
            reject_redirects=reject_redirects,
        )
        if selected_clock() >= deadline:
            close = getattr(response, "close", None)
            if callable(close):
                close()
            raise ResponseOpenDeadlineError(
                "GitHub request open exceeded the time limit"
            )
        return response

    block_live_test_call(urllib.request.urlopen, urllib.request.urlopen)
    redirect_handler = (
        _RejectRedirectHandler()
        if reject_redirects
        else _ExactOriginRedirectHandler(endpoint)
    )
    if replay_safe:
        safe_opener = urllib.request.build_opener(redirect_handler)
        return open_replay_safe(
            request,
            opener=safe_opener.open,
            deadline=deadline,
            clock=selected_clock,
        )
    return open_https_caller_owned(
        request,
        deadline=deadline,
        handlers=(redirect_handler,),
        clock=selected_clock,
    )


__all__ = ["open_same_origin", "open_same_origin_deadline"]
