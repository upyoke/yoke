"""Verify a deployed env's public auth boundary from the outside.

Deployment-verification tool for the first public exposure of a Yoke
core service (stage bringup, future env proofs). Asserts the environment-auth boundary
boundary contract as observed from a plain HTTPS client:

1. ``GET /v1/health`` is public, returns 200, and its payload carries no
   sensitive keys;
2. ``POST /v1/functions/call`` WITHOUT credentials is denied with 401;
3. the same call WITH a bearer token (read from ``--token-file``, never
   argv) is authenticated — any status except 401/403 proves identity
   passed the boundary (the function outcome itself is not the subject).

Usage::

    python3 -m yoke_core.tools.verify_env_auth_boundary \\
        https://app.stage.upyoke.com/api/orgs/yoke-stage --token-file ~/.yoke/secrets/x.json

The token file accepts either the raw token or the bootstrap-admin JSON
payload (``{"raw_token": "..."}``). Exit 0 when every check passes.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
import uuid
from pathlib import Path

from yoke_cli.transport.bounded_json_http import (
    BoundedJsonHttpError,
    BoundedJsonHttpStatusError,
    request_json,
    safe_diagnostic_text,
)

_SENSITIVE_HEALTH_TOKENS = ("dsn", "password", "secret", "token")


def _request(
    url: str,
    *,
    method: str = "GET",
    token: str = "",
    payload: dict | None = None,
    timeout: int = 20,
) -> tuple[int, str]:
    headers = {"x-request-id": str(uuid.uuid4())}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        response = request_json(
            request,
            timeout_seconds=timeout,
            replay_safe=method.upper() in {"GET", "HEAD"},
            allow_loopback_http=True,
            sensitive_values=(token,) if token else (),
            opener=urllib.request.urlopen,
        )
        return response.status, _payload_text(response.payload)
    except BoundedJsonHttpStatusError as exc:
        return exc.status, _payload_text(exc.payload)
    except BoundedJsonHttpError as exc:
        raise RuntimeError(f"auth boundary request failed: {exc}") from None


def _payload_text(payload: object) -> str:
    if payload is None:
        return ""
    if isinstance(payload, str):
        return payload
    return json.dumps(payload, sort_keys=True)


def _read_token(token_file: Path) -> str:
    raw = token_file.read_text(encoding="utf-8").strip()
    if raw.startswith("{"):
        payload = json.loads(raw)
        token = str(payload.get("raw_token") or "")
        if not token:
            raise ValueError(f"{token_file} is JSON but carries no 'raw_token' key")
        return token
    return raw


def _function_call_payload() -> dict:
    return {
        "function": "events.query.run",
        "request_id": str(uuid.uuid4()),
        "actor": {},
        "target": {"kind": "system"},
        "payload": {"limit": 1},
    }


def verify(base_url: str, token: str, emit=print) -> int:
    base = base_url.rstrip("/")
    safe_base = safe_diagnostic_text(base, sensitive_values=(token,))
    failures = 0

    status, body = _request(f"{base}/v1/health")
    lowered = body.lower()
    leaked = [t for t in _SENSITIVE_HEALTH_TOKENS if t in lowered]
    if status == 200 and not leaked:
        emit(f"PASS public health: 200, non-sensitive payload ({safe_base}/v1/health)")
    else:
        failures += 1
        emit(f"FAIL public health: status={status} leaked={leaked}")

    call_url = f"{base}/v1/functions/call"
    status, _body = _request(call_url, method="POST", payload=_function_call_payload())
    if status == 401:
        emit("PASS unauthenticated function call denied with 401")
    else:
        failures += 1
        emit(f"FAIL unauthenticated function call returned {status}, expected 401")

    status, _body = _request(
        call_url, method="POST", token=token, payload=_function_call_payload()
    )
    if status not in (401, 403):
        emit(f"PASS authenticated function call passed the boundary ({status})")
    else:
        failures += 1
        emit(f"FAIL authenticated function call denied with {status}")

    return 1 if failures else 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="verify-env-auth-boundary",
        description="Verify a deployed env's public auth boundary",
    )
    parser.add_argument(
        "base_url",
        help="e.g. https://app.stage.upyoke.com/api/orgs/yoke-stage",
    )
    parser.add_argument(
        "--token-file",
        required=True,
        type=Path,
        help="File carrying the raw bearer token or bootstrap-admin JSON",
    )
    args = parser.parse_args(argv)
    try:
        token = _read_token(args.token_file)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return verify(args.base_url, token)


if __name__ == "__main__":
    sys.exit(main())
