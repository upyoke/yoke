"""Discover and mint browser admission for the active self-host connection."""

from __future__ import annotations

import re
import urllib.request
from typing import Any
from urllib.parse import urlsplit

from yoke_contracts.machine_config import reader as machine_config
from yoke_contracts.onboard_destinations import is_hosted_url
from yoke_contracts.bounded_json_http import (
    BoundedJsonHttpError,
    BoundedJsonHttpStatusError,
    request_json,
)
from yoke_cli.transport.https_credentials import TransportError, resolve_token
from yoke_contracts.response_limits import ONBOARD_JSON_REQUEST_TIMEOUT_SECONDS
from yoke_contracts.api_urls import join_api_url
from yoke_contracts.browser_sign_in import (
    BROWSER_SIGN_IN_MAX_LENGTH,
    BROWSER_SIGN_IN_PATH,
    BROWSER_SIGN_IN_REDEEM_PATH,
)
from yoke_contracts.machine_config.schema import MachineConfigContractError


class BrowserSignInLinkError(RuntimeError):
    """A safe error from the self-host browser admission exchange."""


def self_host_connection() -> dict[str, Any] | None:
    """Return the active self-host connection, or None for every other mode.

    Reads machine config only: no request leaves the machine and no token is
    minted, so status reads can name the self-host workbench cheaply.
    """
    try:
        connection = machine_config.active_connection()
    except (machine_config.MachineConfigError, MachineConfigContractError):
        return None  # The local connection preflight owns config diagnostics.
    if connection.get("transport") != "https":
        return None
    if is_hosted_url(str(connection.get("api_url") or "")):
        return None
    return connection


def self_host_url(connection: dict[str, Any]) -> str:
    """The workbench origin of a self-host connection's API URL."""
    server = urlsplit(str(connection.get("api_url") or ""))
    return f"{server.scheme}://{server.netloc}"


def self_host_sign_in_method(connection: dict[str, Any], *, recovery: str) -> str:
    payload = _request_door(connection, recovery=recovery)
    method = payload.get("auth_method") if isinstance(payload, dict) else None
    if method not in ("oidc", "token"):
        raise _invalid_response(recovery)
    return method


def mint_self_host_sign_in_link(connection: dict[str, Any], *, recovery: str) -> str | None:
    """Return a fresh link for the credential's actor, or None for company sign-in."""
    try:
        token = resolve_token(connection)
    except TransportError:
        raise BrowserSignInLinkError(
            "browser_sign_in_credential_unavailable: configure this connection's API "
            f"token with `yoke auth set`, then {recovery}"
        ) from None
    payload = _request_door(connection, recovery=recovery, token=token)
    method = payload.get("auth_method") if isinstance(payload, dict) else None
    if method == "oidc":
        return None
    path = payload.get("sign_in_path") if isinstance(payload, dict) else None
    if not (
        method == "token"
        and isinstance(path, str)
        and len(path.partition("#")[2]) <= BROWSER_SIGN_IN_MAX_LENGTH
        and re.fullmatch(
            re.escape(BROWSER_SIGN_IN_REDEEM_PATH) + r"#[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+",
            path,
        )
    ):
        raise _invalid_response(recovery)
    return self_host_url(connection) + path


def _invalid_response(recovery: str) -> BrowserSignInLinkError:
    return BrowserSignInLinkError(
        "browser_sign_in_invalid_response: the server returned an invalid admission "
        f"door; ask the server operator to repair it, then {recovery}"
    )


def _request_door(
    connection: dict[str, Any], *, recovery: str, token: str | None = None
) -> Any:
    request = urllib.request.Request(
        join_api_url(str(connection.get("api_url") or ""), BROWSER_SIGN_IN_PATH),
        data=b"" if token is not None else None,
        headers={"Authorization": f"Bearer {token}"} if token is not None else {},
        method="POST" if token is not None else "GET",
    )
    try:
        response = request_json(
            request,
            timeout_seconds=ONBOARD_JSON_REQUEST_TIMEOUT_SECONDS,
            replay_safe=token is None,
            allow_private_http=True,
            sensitive_values=(token,) if token is not None else (),
            opener=urllib.request.urlopen,
        )
    except BoundedJsonHttpStatusError as exc:
        if exc.status == 404:
            raise BrowserSignInLinkError(
                "browser_sign_in_server_version: this server has no browser admission "
                "door; ask the server operator to upgrade to a release supporting "
                f"token browser sign-in, then {recovery}"
            ) from None
        raise BrowserSignInLinkError(
            f"browser_sign_in_refused: the server rejected browser admission (HTTP {exc.status}); "
            f"correct the server or token issue, then {recovery}"
        ) from None
    except BoundedJsonHttpError:
        raise BrowserSignInLinkError(
            "browser_sign_in_unavailable: could not reach the browser admission door; "
            f"restore server connectivity, then {recovery}"
        ) from None
    return response.payload
