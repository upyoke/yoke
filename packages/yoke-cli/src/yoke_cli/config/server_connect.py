"""Verify a Yoke server, then record an https machine-config connection.

``yoke connect URL`` is the attach half of self-hosting (and works
against any Yoke API server): it proves the server is reachable
(``GET /v1/health``) and that the supplied token authenticates
(``GET /v1/auth/identity``) BEFORE persisting anything. Only after both
checks pass does it write the token as a Yoke-owned machine secret file
and the connection entry in machine config, then point ``active_env`` at
the new entry unless the caller opts out.

Scheme policy: HTTPS or private-network HTTP; public HTTP is refused before
credentials leave the machine.
"""

from __future__ import annotations

import ipaddress
import urllib.parse
import urllib.request
from typing import Any, Dict, Mapping, Optional

from yoke_contracts.private_network_http import allows_http_host
from yoke_contracts.refusal_recovery import compose_refusal

from yoke_cli.config import writer
from yoke_cli.transport import server_reach_failure
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


class SourcePausedError(ServerConnectError):
    """A reachable source requires explicit Resume before attachment."""


class ServerIdentityError(RuntimeError):
    """The configured credential could not prove an actor identity."""


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
    try:
        identity = verify_server_identity(
            api_url,
            token=token,
            timeout_s=timeout_s,
        )
    except ServerIdentityError as exc:
        raise ServerConnectError(
            f"{exc}; nothing was persisted — paste the server's initial admin "
            "token (first boot writes it to the bundle's "
            "secrets/first-boot-admin-token), or mint a new one"
        ) from exc

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
        "identity": server_identity_summary(identity),
        "config": connection.get("config"),
    }


def _normalized_api_url(url: str) -> str:
    candidate = str(url or "").strip().rstrip("/")
    if not candidate:
        raise ServerConnectError("server URL is required")
    if not candidate.startswith(_ALLOWED_SCHEMES):
        raise ServerConnectError(
            f"unsupported URL scheme in {candidate!r}: use https:// (normal) "
            "or http:// with a private-network address"
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
    if parsed.scheme.lower() == "http" and not allows_http_host(parsed.hostname):
        raise ServerConnectError(
            "public_http_refused: plain HTTP requires numeric loopback, a private "
            "network address or a *.ts.net name; use the server's https:// URL. "
            + server_reach_failure.CHECK_SERVER_MACHINE
        )
    return candidate


def _verify_health(api_url: str, *, timeout_s: float) -> Mapping[str, Any]:
    health_url = join_api_url(api_url, HEALTH_PATH)
    safe_health_url = safe_diagnostic_text(health_url)
    try:
        payload = _http_get_json(health_url, headers={}, timeout_s=timeout_s)
    except _HttpFailure as exc:
        if exc.named:
            raise ServerConnectError(
                f"{exc} Nothing was persisted ({safe_health_url})."
            ) from exc
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


def verify_server_health(
    api_url: str, *, timeout_s: float = _DEFAULT_TIMEOUT_S
) -> Mapping[str, Any]:
    """Prove ``GET /v1/health`` answers. Does not persist a connection."""
    return _verify_health(_normalized_api_url(api_url), timeout_s=timeout_s)


def verify_server_identity(
    api_url: str,
    *,
    token: str,
    timeout_s: float = _DEFAULT_TIMEOUT_S,
) -> Mapping[str, Any]:
    """Return the actor identity proved by ``token`` at ``api_url``.

    This is the shared read-only probe used by both connection setup and
    status diagnostics. Error text is safe to display and never includes the
    bearer token.
    """
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
        raise ServerIdentityError(
            f"token verification failed ({safe_identity_url}): {exc}"
        ) from exc
    if not isinstance(payload, Mapping):
        raise ServerIdentityError(f"{safe_identity_url} did not return a JSON object")
    return payload


class _HttpFailure(RuntimeError):
    """One HTTP verification request failed (status, network, or body).

    ``named`` marks a reach failure already carrying its code and fix.
    """

    def __init__(self, message: str, *, named: bool = False) -> None:
        self.named = named
        super().__init__(message)


def _http_get_json(url: str, *, headers: Mapping[str, str], timeout_s: float) -> Any:
    """GET ``url`` and parse the JSON body; tests stub this seam."""
    request = urllib.request.Request(url, method="GET", headers=dict(headers))
    try:
        response = request_json(
            request,
            timeout_seconds=timeout_s,
            replay_safe=True,
            allow_private_http=True,
            opener=urllib.request.urlopen,
        )
    except BoundedJsonHttpError as exc:
        failure = server_reach_failure.describe(
            exc, url, check_server_machine=not _is_loopback(url)
        )
        if failure is not None:
            raise _HttpFailure(failure, named=True) from None
        if isinstance(exc, BoundedJsonHttpStatusError):
            payload = exc.payload
            if (
                exc.status == 503
                and isinstance(payload, Mapping)
                and isinstance(payload.get("error"), Mapping)
                and payload["error"].get("code") == "universe_source_paused"
            ):
                raise SourcePausedError(
                    compose_refusal(
                        "universe_source_paused: this server is reachable but its source writers remain paused",
                        recovery="run `yoke universe resume` against the source connection, then retry connection setup",
                    )
                ) from None
            raise _HttpFailure(f"HTTP {exc.status}") from None
        raise _HttpFailure(str(exc)) from None
    return response.payload


def _is_loopback(url: str) -> bool:
    """A loopback server is on this machine, so no other machine to check."""
    try:
        return ipaddress.ip_address(
            urllib.parse.urlsplit(url).hostname or ""
        ).is_loopback
    except ValueError:
        return False


def _health_summary(health: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "status": health.get("status"),
        "build": health.get("build"),
        "schema_ready": health.get("schema_ready"),
    }


def server_identity_summary(identity: Mapping[str, Any]) -> Dict[str, Any]:
    """Return the non-secret identity fields safe for diagnostics."""
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
    "ServerIdentityError",
    "connect_server",
    "server_identity_summary",
    "verify_server_health",
    "verify_server_identity",
]
