"""HTTPS client for process-only runner-fleet installation tokens."""

from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import HTTPRedirectHandler, Request, build_opener

from yoke_cli.api_urls import join_api_url
from yoke_cli.transport.https import HttpsConnection, TransportError
from yoke_contracts.runner_fleet_token import (
    RunnerFleetTokenRequest,
    RunnerFleetTokenResponse,
)

_MAX_RESPONSE_BYTES = 64 * 1024
_TIMEOUT_SECONDS = 30.0


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        del req, fp, code, msg, headers, newurl
        return None


_OPENER = build_opener(_NoRedirect())


def fetch_runner_fleet_token(
    connection: HttpsConnection,
    *,
    project: str,
    authority_intent: str,
    timeout_seconds: float = _TIMEOUT_SECONDS,
) -> str:
    """Fetch one token without following redirects or exposing error bodies."""
    try:
        intent = json.loads(authority_intent)
        digest = str(intent.get("sha256") or "")
        authority = intent.get("authority")
        expected_repository = str(authority.get("repo") or "")
        payload = RunnerFleetTokenRequest(authority_sha256=digest)
    except (AttributeError, TypeError, ValueError) as exc:
        raise TransportError("runner-fleet authority intent is invalid") from exc
    path = f"/v1/projects/{quote(project, safe='')}/runner-fleet-token"
    request = Request(
        join_api_url(connection.api_url, path),
        data=payload.model_dump_json().encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {connection.token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with _OPENER.open(request, timeout=timeout_seconds) as response:
            cache_control = str(response.headers.get("Cache-Control") or "")
            if "no-store" not in cache_control.lower():
                raise TransportError(
                    "runner-fleet token broker response is not marked no-store"
                )
            raw = response.read(_MAX_RESPONSE_BYTES + 1)
    except HTTPError as exc:
        raise TransportError(
            f"runner-fleet token broker returned HTTP {exc.code}"
        ) from None
    except (URLError, TimeoutError, OSError) as exc:
        raise TransportError("runner-fleet token broker is unreachable") from exc
    if len(raw) > _MAX_RESPONSE_BYTES:
        raise TransportError("runner-fleet token broker response is too large")
    try:
        grant = RunnerFleetTokenResponse.model_validate_json(raw)
    except ValueError as exc:
        raise TransportError(
            "runner-fleet token broker returned an invalid response"
        ) from exc
    if not expected_repository or grant.repository != expected_repository:
        raise TransportError(
            "runner-fleet token broker returned a different repository binding"
        )
    token = grant.token.strip()
    if not token:
        raise TransportError("runner-fleet token broker returned an empty token")
    return token


__all__ = ["fetch_runner_fleet_token"]
