"""Authenticated server-authority diagnostics for ``yoke status``."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from yoke_cli.api_urls import HEALTH_PATH, join_api_url
from yoke_cli.config import server_connect
from yoke_cli.transport import https as https_transport
from yoke_contracts.machine_config import schema as contract

SERVER_HEALTH_TIMEOUT_S = 3.0
SERVER_IDENTITY_TIMEOUT_S = 3.0


def fetch_server_health(
    api_url: str,
    *,
    timeout_s: float = SERVER_HEALTH_TIMEOUT_S,
) -> Mapping[str, Any] | None:
    """GET the active server health document; return ``None`` on failure."""
    import urllib.request

    url = join_api_url(api_url, HEALTH_PATH)
    try:
        with urllib.request.urlopen(url, timeout=timeout_s) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:  # noqa: BLE001 - status degrades instead of raising
        return None
    return payload if isinstance(payload, dict) else None


def server_status(
    connection: Mapping[str, Any],
    *,
    config_path: Path,
    explicit_env: str | None,
    check_reachability: bool,
) -> dict[str, Any]:
    """Prove the active HTTPS authority is alive and authenticated.

    Local Postgres has no HTTP server. Loopback local servers, self-hosted
    servers, and hosted org relays all use the same HTTPS credential resolver
    as ordinary product commands.
    """
    if str(connection.get("transport") or "") != contract.TRANSPORT_HTTPS:
        return _report(relevant=False)
    api_url = str(connection.get("api_url") or "")
    if not api_url or not check_reachability:
        return _report(relevant=True, authority=api_url)
    health = fetch_server_health(api_url)
    if health is None:
        return _report(
            relevant=True,
            reachable=False,
            authority=api_url,
            issues=[_issue(
                "warning",
                "server_unreachable",
                f"health probe failed against {api_url}",
                "Check the api_url and network; the server may be down.",
            )],
        )

    try:
        resolved = https_transport.resolve_https_connection(
            config_path,
            explicit_env=explicit_env,
        )
        if resolved is None:
            raise https_transport.TransportError(
                "active HTTPS connection did not resolve"
            )
        identity = server_connect.verify_server_identity(
            resolved.api_url,
            token=resolved.token,
            timeout_s=SERVER_IDENTITY_TIMEOUT_S,
        )
    except (
        https_transport.TransportError,
        server_connect.ServerIdentityError,
    ) as exc:
        return _report(
            relevant=True,
            reachable=True,
            engine_version=str(health.get("engine_version") or ""),
            build=str(health.get("build") or ""),
            authority=api_url,
            identity_verified=False,
            issues=[_issue(
                "error",
                "server_identity_unverified",
                f"authenticated identity probe failed against {api_url}: {exc}",
                "Run `yoke connect` and select the intended authority; "
                "a green health endpoint alone does not prove the tenant.",
            )],
        )

    summary = server_connect.server_identity_summary(identity)
    return _report(
        relevant=True,
        reachable=True,
        engine_version=str(health.get("engine_version") or ""),
        build=str(health.get("build") or ""),
        authority=resolved.api_url,
        identity_verified=True,
        actor=summary["actor"],
        token_name=summary["token_name"],
    )


def _report(
    *,
    relevant: bool,
    reachable: bool | None = None,
    engine_version: str = "",
    build: str = "",
    authority: str = "",
    identity_verified: bool | None = None,
    actor: Mapping[str, Any] | None = None,
    token_name: Any = None,
    issues: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    return {
        "relevant": relevant,
        "reachable": reachable,
        "engine_version": engine_version,
        "build": build,
        "authority": authority,
        "identity_verified": identity_verified,
        "actor": dict(actor or {}),
        "token_name": token_name,
        "issues": list(issues or []),
    }


def _issue(
    severity: str,
    code: str,
    message: str,
    hint: str = "",
) -> dict[str, str]:
    issue = {"severity": severity, "code": code, "message": message}
    if hint:
        issue["hint"] = hint
    return issue


__all__ = ["fetch_server_health", "server_status"]
