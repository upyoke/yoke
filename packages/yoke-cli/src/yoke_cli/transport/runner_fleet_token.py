"""HTTPS client for process-only runner-fleet installation tokens."""

from __future__ import annotations

import json
from urllib.parse import quote
from urllib.request import Request, build_opener

from yoke_cli.api_urls import join_api_url
from yoke_cli.transport.https import HttpsConnection, TransportError
from yoke_cli.transport.bounded_json_http import (
    BoundedJsonHttpDeadlineError,
    BoundedJsonHttpError,
    BoundedJsonHttpStatusError,
    request_json,
)
from yoke_cli.transport.https_urlopen import NoRedirect
from yoke_cli.transport.response_limits import (
    DEFAULT_JSON_REQUEST_TIMEOUT_SECONDS,
    SMALL_JSON_RESPONSE_LIMIT_BYTES,
)
from yoke_contracts.runner_fleet_token import (
    RunnerFleetTokenRequest,
    RunnerFleetTokenResponse,
)

_TIMEOUT_SECONDS = DEFAULT_JSON_REQUEST_TIMEOUT_SECONDS

_OPENER = build_opener(NoRedirect())
_DEFAULT_OPENER = _OPENER


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
        response = request_json(
            request,
            timeout_seconds=timeout_seconds,
            replay_safe=False,
            allow_loopback_http=True,
            response_limit_bytes=SMALL_JSON_RESPONSE_LIMIT_BYTES,
            sensitive_values=(connection.token,),
            opener=None if _OPENER is _DEFAULT_OPENER else _OPENER.open,
        )
    except BoundedJsonHttpStatusError as exc:
        raise TransportError(
            f"runner-fleet token broker returned HTTP {exc.status}"
        ) from None
    except BoundedJsonHttpDeadlineError:
        raise TransportError(
            "runner-fleet token broker response exceeded the time limit"
        ) from None
    except BoundedJsonHttpError as exc:
        raise TransportError(
            f"runner-fleet token broker returned an invalid response: {exc}"
        ) from None
    cache_control = str(response.headers.get("Cache-Control") or "")
    if "no-store" not in cache_control.lower():
        raise TransportError(
            "runner-fleet token broker response is not marked no-store"
        )
    try:
        grant = RunnerFleetTokenResponse.model_validate(response.payload)
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
