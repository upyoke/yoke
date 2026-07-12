"""Opening and final-URL policy for bounded hosted HTTP requests."""

from __future__ import annotations

import ipaddress
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

from yoke_cli.transport.https_urlopen import NoRedirect, open_no_redirect
from yoke_cli.transport.response_deadline_open import (
    open_caller_owned,
    open_https_caller_owned,
    open_replay_safe,
)


_DEFAULT_URLOPEN = urllib.request.urlopen
_LOOPBACK_OPENER = urllib.request.build_opener(
    urllib.request.ProxyHandler({}),
    NoRedirect(),
)


class HttpOpenPolicyError(ValueError):
    """The requested endpoint cannot safely use the selected open policy."""


class HttpFinalUrlError(ValueError):
    """An opened response did not prove it stayed on the requested URL."""


def open_bounded_request(
    request: urllib.request.Request,
    *,
    deadline: float,
    replay_safe: bool,
    allow_loopback_http: bool,
    opener: Callable[..., Any] | None,
) -> Any:
    """Open one request with redirect denial and method-aware ownership."""

    scheme = _validated_scheme(
        request.full_url,
        allow_loopback_http=allow_loopback_http,
    )
    selected_opener = opener or _DEFAULT_URLOPEN
    if selected_opener is not _DEFAULT_URLOPEN:
        if replay_safe:
            return open_replay_safe(
                request,
                opener=selected_opener,
                deadline=deadline,
            )
        return open_caller_owned(
            request,
            opener=selected_opener,
            deadline=deadline,
        )
    if scheme == "https":
        if replay_safe:
            return open_replay_safe(
                request,
                opener=open_no_redirect,
                deadline=deadline,
            )
        return open_https_caller_owned(
            request,
            deadline=deadline,
            handlers=(NoRedirect(),),
        )
    if replay_safe:
        return open_replay_safe(
            request,
            opener=_LOOPBACK_OPENER.open,
            deadline=deadline,
        )
    return open_caller_owned(
        request,
        opener=_LOOPBACK_OPENER.open,
        deadline=deadline,
    )


def require_requested_final_url(
    request: urllib.request.Request,
    response: Any,
) -> None:
    """Require a response to report the exact normalized requested URL."""

    geturl = getattr(response, "geturl", None)
    if not callable(geturl):
        raise HttpFinalUrlError("JSON response did not report its final URL")
    try:
        requested = _normalized_response_url(request.full_url)
        final = _normalized_response_url(geturl())
    except (TypeError, ValueError):
        raise HttpFinalUrlError("JSON response reported an invalid final URL") from None
    if final != requested:
        raise HttpFinalUrlError("JSON response final URL did not match the request URL")


def _validated_scheme(url: str, *, allow_loopback_http: bool) -> str:
    try:
        parsed = urllib.parse.urlsplit(url)
        port = parsed.port
    except (TypeError, ValueError) as exc:
        raise HttpOpenPolicyError("JSON request endpoint is not a valid URL") from exc
    scheme = parsed.scheme.lower()
    if (
        not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise HttpOpenPolicyError(
            "JSON request endpoint must name a host without URL credentials"
        )
    if parsed.fragment:
        raise HttpOpenPolicyError("JSON request endpoint must not contain a fragment")
    if scheme == "https":
        return scheme
    if scheme != "http" or not allow_loopback_http:
        raise HttpOpenPolicyError("credential-bearing JSON requests require HTTPS")
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError as exc:
        raise HttpOpenPolicyError(
            "plain HTTP JSON requests require a numeric loopback address"
        ) from exc
    if not address.is_loopback:
        raise HttpOpenPolicyError(
            "plain HTTP JSON requests require a numeric loopback address"
        )
    if port is not None and not 1 <= port <= 65535:
        raise HttpOpenPolicyError("JSON request endpoint port is invalid")
    return scheme


def _normalized_response_url(value: Any) -> str:
    parsed = urllib.parse.urlsplit(str(value))
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise ValueError("invalid response URL")
    port = parsed.port
    scheme = parsed.scheme.lower()
    host = parsed.hostname.casefold()
    rendered_host = f"[{host}]" if ":" in host else host
    default_port = 443 if scheme == "https" else 80
    netloc = (
        rendered_host if port in {None, default_port} else f"{rendered_host}:{port}"
    )
    return urllib.parse.urlunsplit(
        (scheme, netloc, parsed.path or "/", parsed.query, "")
    )


__all__ = [
    "HttpFinalUrlError",
    "HttpOpenPolicyError",
    "NoRedirect",
    "open_bounded_request",
    "open_no_redirect",
    "require_requested_final_url",
]
