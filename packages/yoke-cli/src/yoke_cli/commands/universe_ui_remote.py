"""Open a self-host workbench using the active connection's credential."""

from __future__ import annotations

import re
import urllib.request
from typing import Any
from urllib.parse import urlsplit

from yoke_cli.commands.universe_ui_connection import UniverseUiError
from yoke_cli.config import machine_config
from yoke_cli.config.onboard_destinations import is_hosted_url
from yoke_cli.transport.bounded_json_http import (
    BoundedJsonHttpError,
    BoundedJsonHttpStatusError,
    error_detail,
    request_json,
)
from yoke_cli.transport.https_credentials import TransportError, resolve_token
from yoke_cli.transport.response_limits import ONBOARD_JSON_REQUEST_TIMEOUT_SECONDS
from yoke_contracts.api_urls import join_api_url
from yoke_contracts.browser_sign_in import (
    BROWSER_SIGN_IN_MAX_LENGTH,
    BROWSER_SIGN_IN_PATH,
    BROWSER_SIGN_IN_REDEEM_PATH,
)
from yoke_contracts.machine_config.schema import MachineConfigContractError


def self_host_report(*, host: str | None, port: int | None) -> dict[str, Any] | None:
    """Return a private browser door for self-host; other modes keep their path."""
    try:
        connection = machine_config.active_connection()
    except (machine_config.MachineConfigError, MachineConfigContractError):
        return None  # The local connection preflight owns config diagnostics.
    if connection.get("transport") != "https":
        return None
    api_url = str(connection.get("api_url") or "")
    if is_hosted_url(api_url):
        return None
    if host is not None or port is not None:
        raise UniverseUiError(
            "self_host_ui_local_flags: --host and --port configure a local daemon; "
            "run `yoke ui up` without them to open this server"
        )
    discovery = _request_door(api_url)
    method = discovery.get("auth_method") if isinstance(discovery, dict) else None
    if method == "oidc":
        path = "/"
    elif method == "token":
        try:
            token = resolve_token(connection)
        except TransportError as exc:
            raise UniverseUiError(
                f"browser_sign_in_credential_unavailable: {exc}"
            ) from None
        payload = _request_door(api_url, token)
        path = payload.get("sign_in_path") if isinstance(payload, dict) else None
        # OIDC may have been enabled between discovery and exchange.
        method = payload.get("auth_method") if isinstance(payload, dict) else None
    else:
        path = None
    valid = (method == "oidc" and path == "/") or (
        method == "token"
        and isinstance(path, str)
        and len(path.partition("#")[2]) <= BROWSER_SIGN_IN_MAX_LENGTH
        and re.fullmatch(
            re.escape(BROWSER_SIGN_IN_REDEEM_PATH) + r"#[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+",
            path,
        )
    )
    if not valid:
        raise UniverseUiError(
            "browser_sign_in_invalid_response: the server returned an invalid admission door; "
            "ask the server operator to repair it, then run `yoke ui up` again"
        )
    server = urlsplit(api_url)
    return {
        "mode": "self-host",
        "env": connection.get("env"),
        "auth_method": method,
        "private_url": f"{server.scheme}://{server.netloc}{path}",
    }


def _request_door(api_url: str, token: str | None = None) -> Any:
    request = urllib.request.Request(
        join_api_url(api_url, BROWSER_SIGN_IN_PATH),
        data=b"" if token is not None else None,
        headers={"Authorization": f"Bearer {token}"} if token is not None else {},
        method="POST" if token is not None else "GET",
    )
    try:
        response = request_json(
            request,
            timeout_seconds=ONBOARD_JSON_REQUEST_TIMEOUT_SECONDS,
            replay_safe=token is None,
            allow_loopback_http=True,
            sensitive_values=(token,) if token is not None else (),
            opener=urllib.request.urlopen,
        )
    except BoundedJsonHttpStatusError as exc:
        if exc.status == 404:
            raise UniverseUiError(
                "browser_sign_in_server_version: this server has no browser admission door; "
                "ask the server operator to upgrade to a release supporting token browser sign-in, "
                "then run `yoke ui up` again"
            ) from None
        raise UniverseUiError(
            f"browser_sign_in_refused: {error_detail(exc.payload)} "
            "Run `yoke ui up` again after correcting the server or token issue."
        ) from None
    except BoundedJsonHttpError as exc:
        raise UniverseUiError(
            f"browser_sign_in_unavailable: {exc}; restore server connectivity, "
            "then run `yoke ui up` again"
        ) from None
    return response.payload
