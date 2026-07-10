"""Hosted function transport for existing-project discovery."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
import uuid
from typing import Any, Mapping

from yoke_cli.api_urls import FUNCTIONS_CALL_PATH, join_api_url

_TIMEOUT_S = 20.0


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
    body = json.dumps({
        "function": function,
        "version": "v1",
        "actor": {"actor_id": None, "session_id": ""},
        "target": {"kind": "global"},
        "request_id": str(uuid.uuid4()),
        "payload": dict(payload),
        "preconditions": {},
        "options": {},
    }).encode("utf-8")
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
        with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        try:
            raw = exc.read().decode("utf-8")
        except Exception:
            raw = ""
        if raw:
            try:
                error_payload = json.loads(raw)
            except ValueError:
                error_payload = {}
            if isinstance(error_payload, Mapping):
                return error_payload
        raise ExistingProjectLookupError(
            f"{function} lookup returned HTTP {exc.code}"
        ) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ExistingProjectLookupError(str(exc)) from exc
    try:
        parsed = json.loads(raw) if raw else {}
    except ValueError as exc:
        raise ExistingProjectLookupError(f"{function} returned invalid JSON") from exc
    if not isinstance(parsed, Mapping):
        raise ExistingProjectLookupError(f"{function} returned a non-object response")
    return parsed


__all__ = ["ExistingProjectLookupError", "call_function"]
