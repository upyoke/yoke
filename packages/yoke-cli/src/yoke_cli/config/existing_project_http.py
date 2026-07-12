"""Hosted function transport for existing-project discovery."""

from __future__ import annotations

import json
import urllib.request
import uuid
from typing import Any, Mapping

from yoke_cli.api_urls import FUNCTIONS_CALL_PATH, join_api_url
from yoke_cli.transport.bounded_json_http import (
    BoundedJsonHttpError,
    BoundedJsonHttpStatusError,
    request_json,
    safe_diagnostic_text,
)
from yoke_cli.transport.response_limits import ONBOARD_JSON_REQUEST_TIMEOUT_SECONDS

_TIMEOUT_S = ONBOARD_JSON_REQUEST_TIMEOUT_SECONDS


class ExistingProjectLookupError(RuntimeError):
    """The API lookup for an existing project could not complete."""


def call_function(
    *,
    api_url: str,
    token: str,
    function: str,
    payload: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Call one hosted project lookup function and return its response object."""
    body = json.dumps(
        {
            "function": function,
            "version": "v1",
            "actor": {"actor_id": None, "session_id": ""},
            "target": {"kind": "global"},
            "request_id": str(uuid.uuid4()),
            "payload": dict(payload),
            "preconditions": {},
            "options": {},
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        join_api_url(api_url, FUNCTIONS_CALL_PATH),
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
    )
    try:
        response = request_json(
            request,
            timeout_seconds=_TIMEOUT_S,
            replay_safe=False,
            allow_loopback_http=True,
            sensitive_values=(token,),
            opener=urllib.request.urlopen,
        )
    except BoundedJsonHttpStatusError as exc:
        if isinstance(exc.payload, Mapping):
            return exc.payload
        raise ExistingProjectLookupError(
            f"{safe_diagnostic_text(function)} lookup returned HTTP {exc.status}"
        ) from None
    except BoundedJsonHttpError as exc:
        raise ExistingProjectLookupError(
            f"{safe_diagnostic_text(function)} lookup failed: {exc}"
        ) from None
    parsed = response.payload if response.payload is not None else {}
    if not isinstance(parsed, Mapping):
        raise ExistingProjectLookupError(
            f"{safe_diagnostic_text(function)} returned a non-object response"
        )
    return parsed


__all__ = ["ExistingProjectLookupError", "call_function"]
