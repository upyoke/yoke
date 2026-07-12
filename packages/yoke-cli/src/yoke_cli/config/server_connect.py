"""Verify a Yoke server, then record an https machine-config connection.

``yoke connect URL`` is the attach half of self-hosting (and works
against any Yoke API server): it proves the server is reachable
(``GET /v1/health``) and that the supplied token authenticates
(``GET /v1/auth/identity``) BEFORE persisting anything. Only after both
checks pass does it write the token as a Yoke-owned machine secret file
and the connection entry in machine config, then point ``active_env`` at
the new entry unless the caller opts out.

Scheme policy: ``https://`` is the normal shape. Plain ``http://`` is
accepted only for a numeric loopback endpoint (for example,
``http://127.0.0.1``). Any other scheme or non-loopback plaintext target is
refused before the actor credential leaves the machine.
"""

from __future__ import annotations

import ipaddress
import urllib.parse
import urllib.request
from typing import Any, Dict, Mapping, Optional

from yoke_cli.config import writer
from yoke_cli.transport.bounded_json_http import (
    BoundedJsonHttpError,
    BoundedJsonHttpStatusError,
    request_json,
    safe_diagnostic_text,
)
from yoke_contracts.api_urls import (
    AUTH_IDENTITY_PATH,
    HEALTH_PATH,
    join_api_url,
)
from yoke_contracts.machine_config.schema_transport import TRANSPORT_HTTPS

#: Default machine-config env label for a server attached via ``yoke
#: connect`` — the primary use is attaching to a self-hosted server.
DEFAULT_ENV_NAME = "self-host"

_ALLOWED_SCHEMES = ("https://", "http://")
_DEFAULT_TIMEOUT_S = 15.0


class ServerConnectError(RuntimeError):
    """Verification or persistence failed; nothing was persisted on
    verification failure."""


def connect_server(
    url: str,
    *,
    token: str,
    env: str = DEFAULT_ENV_NAME,
    activate: bool = True,
    config_path: Optional[str] = None,
    timeout_s: float = _DEFAULT_TIMEOUT_S,
) -> Dict[str, Any]:
    """Verify ``url`` + ``token``, then persist the connection entry."""
    api_url = _normalized_api_url(url)
    if not token.strip():
        raise ServerConnectError("token is empty")

    health = _verify_health(api_url, timeout_s=timeout_s)
    identity = _verify_identity(api_url, token=token, timeout_s=timeout_s)

    try:
        connection = writer.set_connection(
            env,
            transport=TRANSPORT_HTTPS,
            api_url=api_url,
            token=token,
            replace=True,
            path=config_path,
        )
        if activate:
            writer.set_active_env(env, path=config_path)
    except writer.MachineConfigWriteError as exc:
        raise ServerConnectError(str(exc)) from exc

    return {
        "ok": True,
        "env": env,
        "api_url": api_url,
        "active_env": connection.get("active_env") if not activate else env,
        "activated": activate,
        "health": _health_summary(health),
        "identity": _identity_summary(identity),
        "config": connection.get("config"),
    }


def _normalized_api_url(url: str) -> str:
    candidate = str(url or "").strip().rstrip("/")
    if not candidate:
        raise ServerConnectError("server URL is required")
    if not candidate.startswith(_ALLOWED_SCHEMES):
        raise ServerConnectError(
            f"unsupported URL scheme in {candidate!r}: use https:// (normal) "
            "or http:// with a numeric loopback address"
        )
    try:
        parsed = urllib.parse.urlsplit(candidate)
        parsed.port
    except ValueError as exc:
        raise ServerConnectError("server URL is invalid") from exc
    if (
        not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ServerConnectError("server URL must name a host without credentials")
    if parsed.scheme.lower() == "http":
        try:
            address = ipaddress.ip_address(parsed.hostname)
        except ValueError as exc:
            raise ServerConnectError(
                "plain HTTP server URLs require a numeric loopback address"
            ) from exc
        if not address.is_loopback:
            raise ServerConnectError(
                "plain HTTP server URLs require a numeric loopback address"
            )
    return candidate


def _verify_health(api_url: str, *, timeout_s: float) -> Mapping[str, Any]:
    health_url = join_api_url(api_url, HEALTH_PATH)
    safe_health_url = safe_diagnostic_text(health_url)
    try:
        payload = _http_get_json(health_url, headers={}, timeout_s=timeout_s)
    except _HttpFailure as exc:
        raise ServerConnectError(
            f"server health check failed ({safe_health_url}): {exc}; nothing was "
            "persisted — verify the URL and that the server is running "
            "(docker compose ps / docker compose logs core)"
        ) from exc
    if not isinstance(payload, Mapping):
        raise ServerConnectError(
            f"{safe_health_url} did not return a JSON object; nothing was "
            "persisted — is this a Yoke API server?"
        )
    return payload


def _verify_identity(
    api_url: str, *, token: str, timeout_s: float
) -> Mapping[str, Any]:
    identity_url = join_api_url(api_url, AUTH_IDENTITY_PATH)
    safe_identity_url = safe_diagnostic_text(
        identity_url,
        sensitive_values=(token,),
    )
    try:
        payload = _http_get_json(
            identity_url,
            headers={"Authorization": f"Bearer {token}"},
            timeout_s=timeout_s,
        )
    except _HttpFailure as exc:
        raise ServerConnectError(
            f"token verification failed ({safe_identity_url}): {exc}; nothing "
            "was persisted — paste the server's initial admin token (first "
            "boot prints it: docker compose logs core), or mint a new one"
        ) from exc
    if not isinstance(payload, Mapping):
        raise ServerConnectError(
            f"{safe_identity_url} did not return a JSON object; nothing was persisted"
        )
    return payload


class _HttpFailure(RuntimeError):
    """One HTTP verification request failed (status, network, or body)."""


def _http_get_json(url: str, *, headers: Mapping[str, str], timeout_s: float) -> Any:
    """GET ``url`` and parse the JSON body; tests stub this seam."""
    request = urllib.request.Request(url, method="GET", headers=dict(headers))
    try:
        response = request_json(
            request,
            timeout_seconds=timeout_s,
            replay_safe=True,
            allow_loopback_http=True,
            opener=urllib.request.urlopen,
        )
    except BoundedJsonHttpStatusError as exc:
        raise _HttpFailure(f"HTTP {exc.status}") from None
    except BoundedJsonHttpError as exc:
        raise _HttpFailure(str(exc)) from None
    return response.payload


def _health_summary(health: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "status": health.get("status"),
        "build": health.get("build"),
        "schema_ready": health.get("schema_ready"),
    }


def _identity_summary(identity: Mapping[str, Any]) -> Dict[str, Any]:
    actor = identity.get("actor")
    actor = actor if isinstance(actor, Mapping) else {}
    token_info = identity.get("token")
    token_info = token_info if isinstance(token_info, Mapping) else {}
    return {
        "actor": {"id": actor.get("id"), "label": actor.get("label")},
        "token_name": token_info.get("name"),
    }


__all__ = [
    "DEFAULT_ENV_NAME",
    "ServerConnectError",
    "connect_server",
]
