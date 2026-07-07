"""Verify a Yoke server, then record an https machine-config connection.

``yoke connect URL`` is the attach half of self-hosting (and works
against any Yoke API server): it proves the server is reachable
(``GET /v1/health``) and that the supplied token authenticates
(``GET /v1/auth/identity``) BEFORE persisting anything. Only after both
checks pass does it write the token as a Yoke-owned machine secret file
and the connection entry in machine config, then point ``active_env`` at
the new entry unless the caller opts out.

Scheme policy: ``https://`` is the normal shape. Plain ``http://`` is
accepted deliberately — self-host TLS commonly terminates at a reverse
proxy in front of the server, and loopback connects (``http://127.0.0.1``)
must work out of the box. Any other scheme is refused.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Dict, Mapping, Optional

from yoke_cli.config import writer
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
            "or http:// (self-host behind a TLS-terminating proxy, or "
            "loopback)"
        )
    return candidate


def _verify_health(api_url: str, *, timeout_s: float) -> Mapping[str, Any]:
    health_url = join_api_url(api_url, HEALTH_PATH)
    try:
        payload = _http_get_json(health_url, headers={}, timeout_s=timeout_s)
    except _HttpFailure as exc:
        raise ServerConnectError(
            f"server health check failed ({health_url}): {exc}; nothing was "
            "persisted — verify the URL and that the server is running "
            "(docker compose ps / docker compose logs core)"
        ) from exc
    if not isinstance(payload, Mapping):
        raise ServerConnectError(
            f"{health_url} did not return a JSON object; nothing was "
            "persisted — is this a Yoke API server?"
        )
    return payload


def _verify_identity(
    api_url: str, *, token: str, timeout_s: float
) -> Mapping[str, Any]:
    identity_url = join_api_url(api_url, AUTH_IDENTITY_PATH)
    try:
        payload = _http_get_json(
            identity_url,
            headers={"Authorization": f"Bearer {token}"},
            timeout_s=timeout_s,
        )
    except _HttpFailure as exc:
        raise ServerConnectError(
            f"token verification failed ({identity_url}): {exc}; nothing "
            "was persisted — paste the server's initial admin token (first "
            "boot prints it: docker compose logs core), or mint a new one"
        ) from exc
    if not isinstance(payload, Mapping):
        raise ServerConnectError(
            f"{identity_url} did not return a JSON object; nothing was "
            "persisted"
        )
    return payload


class _HttpFailure(RuntimeError):
    """One HTTP verification request failed (status, network, or body)."""


def _http_get_json(
    url: str, *, headers: Mapping[str, str], timeout_s: float
) -> Any:
    """GET ``url`` and parse the JSON body; tests stub this seam."""
    request = urllib.request.Request(url, method="GET", headers=dict(headers))
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        raise _HttpFailure(f"HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise _HttpFailure(str(exc)) from exc
    try:
        return json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise _HttpFailure(f"response body is not JSON: {exc}") from exc


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
