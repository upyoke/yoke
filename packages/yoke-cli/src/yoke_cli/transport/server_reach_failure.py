"""Name why a Yoke server URL could not be used, and how to find out more.

A failed connection to a server reads the same to a person whether the
name did not resolve, nothing listened, TLS failed, or something other than
Yoke answered. Each needs a different fix, so each gets its own code. A
local install on the other machine is the common surprise: it answers on
that machine alone, so the recovery points at ``yoke status`` there, which
says ``local: reachable here only`` when that is the case.
"""

from __future__ import annotations

import urllib.parse
from collections.abc import Mapping
from typing import Any

from yoke_cli.transport.bounded_json_http import (
    NETWORK_NAME_UNRESOLVED,
    NETWORK_NOT_HTTP,
    NETWORK_REFUSED,
    NETWORK_TIMED_OUT,
    NETWORK_TLS,
    BoundedJsonHttpBodyError,
    BoundedJsonHttpDeadlineError,
    BoundedJsonHttpError,
    BoundedJsonHttpNetworkError,
    BoundedJsonHttpStatusError,
)

SERVER_NAME_UNRESOLVED = "server_name_unresolved"
SERVER_TIMED_OUT = "server_timed_out"
SERVER_REFUSED = "server_refused"
SERVER_HTTPS_FAILED = "server_https_failed"
SERVER_NOT_YOKE = "server_not_yoke"
SERVER_UNREACHABLE = "server_unreachable"

#: The refusal a local install's dashboard (``yoke ui up``) gives any caller
#: without its per-run token: proof the URL names a dashboard, not a server.
LOCAL_DASHBOARD_ERROR_CODE = "session_token_required"

#: The step that tells a person what the other machine actually serves.
CHECK_SERVER_MACHINE = (
    "Run `yoke status` on the server's machine to see what it serves. "
    "If it says `local: reachable here only`, that install accepts no other "
    "computer; run `yoke setup` there and pick Host a server here."
)


def describe(
    exc: BoundedJsonHttpError, url: str, *, check_server_machine: bool
) -> str | None:
    """``code: what failed; fix`` for a reach failure, else ``None``.

    ``None`` leaves an HTTP status other than 404 to its caller, which knows
    what that endpoint's statuses mean.
    """
    host = urllib.parse.urlsplit(url).netloc or url
    failure = _failure(exc, host)
    if failure is None:
        return None
    return f"{failure} {CHECK_SERVER_MACHINE}" if check_server_machine else failure


def _failure(exc: BoundedJsonHttpError, host: str) -> str | None:
    if isinstance(exc, BoundedJsonHttpDeadlineError):
        return _timed_out(host)
    if isinstance(exc, BoundedJsonHttpNetworkError):
        if exc.reason == NETWORK_NAME_UNRESOLVED:
            return (
                f"{SERVER_NAME_UNRESOLVED}: no address was found for {host}; "
                "check the spelling, and that this computer is on the network "
                "(VPN or tailnet) that names it."
            )
        if exc.reason == NETWORK_TIMED_OUT:
            return _timed_out(host)
        if exc.reason == NETWORK_REFUSED:
            return (
                f"{SERVER_REFUSED}: {host} refused the connection, so nothing "
                "is listening there for other computers; check the port and "
                "that the server is running."
            )
        if exc.reason == NETWORK_TLS:
            return (
                f"{SERVER_HTTPS_FAILED}: the HTTPS connection to {host} failed "
                f"({exc}); check that the server serves HTTPS on that port "
                "with a certificate for that name."
            )
        if exc.reason == NETWORK_NOT_HTTP:
            return _not_yoke(host, "it did not answer as a web server")
        return (
            f"{SERVER_UNREACHABLE}: {host} could not be reached ({exc}); "
            "check the address and this computer's network."
        )
    if isinstance(exc, BoundedJsonHttpStatusError):
        if _error_code(exc.payload) == LOCAL_DASHBOARD_ERROR_CODE:
            return _not_yoke(
                host,
                "it is a local install's dashboard, reachable on its own machine only",
            )
        if exc.status == 404:
            return _not_yoke(host, "it has no Yoke API at that address (HTTP 404)")
    if isinstance(exc, BoundedJsonHttpBodyError):
        return _not_yoke(host, "its answer was not Yoke's JSON")
    return None


def _error_code(payload: Any) -> str:
    error = payload.get("error") if isinstance(payload, Mapping) else None
    return str(error.get("code") or "") if isinstance(error, Mapping) else ""


def _timed_out(host: str) -> str:
    return (
        f"{SERVER_TIMED_OUT}: {host} did not answer in time; check the "
        "address, the port and any firewall between the two computers."
    )


def _not_yoke(host: str, why: str) -> str:
    return (
        f"{SERVER_NOT_YOKE}: {host} answered, but not as a Yoke server: {why}; "
        "check that the URL names the Yoke server itself."
    )


__all__ = [
    "CHECK_SERVER_MACHINE",
    "SERVER_HTTPS_FAILED",
    "SERVER_NAME_UNRESOLVED",
    "SERVER_NOT_YOKE",
    "SERVER_REFUSED",
    "SERVER_TIMED_OUT",
    "SERVER_UNREACHABLE",
    "describe",
]
