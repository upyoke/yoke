"""Redirect-free, deadline-bounded JSON requests for hosted clients.

The transport distinguishes replay-safe reads from caller-owned mutations:
GET/HEAD opens may be fenced in a daemon worker, while POST opens stay on the
calling thread after a deadline-bounded DNS-only HTTPS preflight.  Plain HTTP
is restricted to numeric loopback addresses and bypasses ambient proxies.
"""

from __future__ import annotations

import http.client
import json
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from yoke_cli.transport.bounded_http_open_policy import (
    HttpFinalUrlError,
    HttpOpenPolicyError,
    open_bounded_request,
    require_requested_final_url,
)
from yoke_cli.transport.json_error_safety import (
    decode_error_payload,
    error_detail,
    request_secrets,
    safe_diagnostic_text,
)
from yoke_cli.transport.response_deadline_open import (
    ResponseOpenDeadlineError,
    ResponseOpenError,
)
from yoke_cli.transport.response_deadline_read import (
    ResponseReadDeadlineError,
    ResponseReadError,
    deadline_after,
    read_response_body,
)
from yoke_cli.transport.response_limits import DEFAULT_JSON_RESPONSE_LIMIT_BYTES


class BoundedJsonHttpError(RuntimeError):
    """One hosted JSON request failed without exposing response bytes."""


class BoundedJsonHttpConfigurationError(BoundedJsonHttpError):
    """The endpoint or request policy is unsafe or malformed."""


class BoundedJsonHttpDeadlineError(BoundedJsonHttpError):
    """The DNS/open/body operation exceeded its one absolute deadline."""


class BoundedJsonHttpNetworkError(BoundedJsonHttpError):
    """The endpoint could not be reached."""


class BoundedJsonHttpBodyError(BoundedJsonHttpError):
    """The response body was oversized or was not valid JSON."""


class BoundedJsonHttpStatusError(BoundedJsonHttpError):
    """The endpoint returned a non-success status and a scrubbed payload."""

    def __init__(self, status: int, payload: Any = None) -> None:
        self.status = int(status)
        self.payload = payload
        super().__init__(f"HTTP {self.status}")


@dataclass(frozen=True)
class BoundedJsonHttpResponse:
    """One successful response after its bounded body has been decoded."""

    payload: Any
    status: int
    headers: Mapping[str, str]


def request_json(
    request: urllib.request.Request,
    *,
    timeout_seconds: float,
    replay_safe: bool,
    allow_loopback_http: bool = False,
    response_limit_bytes: int = DEFAULT_JSON_RESPONSE_LIMIT_BYTES,
    sensitive_values: Iterable[str] = (),
    opener: Callable[..., Any] | None = None,
) -> BoundedJsonHttpResponse:
    """Open, bound, and decode one JSON request under one absolute deadline."""

    method = request.get_method().upper()
    if replay_safe and method not in {"GET", "HEAD"}:
        raise BoundedJsonHttpConfigurationError(
            "only GET or HEAD requests may use replay-safe opening"
        )
    if isinstance(response_limit_bytes, bool) or not isinstance(
        response_limit_bytes, int
    ):
        raise BoundedJsonHttpConfigurationError(
            "JSON response byte limit must be a positive integer"
        )
    if response_limit_bytes <= 0:
        raise BoundedJsonHttpConfigurationError(
            "JSON response byte limit must be a positive integer"
        )
    try:
        deadline = deadline_after(timeout_seconds)
    except ValueError as exc:
        raise BoundedJsonHttpConfigurationError(
            "JSON request timeout must be positive and finite"
        ) from exc

    secrets = request_secrets(request, sensitive_values)
    try:
        opened = open_bounded_request(
            request,
            deadline=deadline,
            replay_safe=replay_safe,
            allow_loopback_http=allow_loopback_http,
            opener=opener,
        )
        with opened as response:
            _require_final_url(request, response)
            raw = _read_bounded_body(
                response,
                deadline=deadline,
                limit_bytes=response_limit_bytes,
            )
            status = _response_status(response)
            headers = _response_headers(response)
    except urllib.error.HTTPError as exc:
        try:
            _require_final_url(request, exc)
            if exc.fp is None:
                raw = b""
            else:
                try:
                    raw = _read_bounded_body(
                        exc,
                        deadline=deadline,
                        limit_bytes=response_limit_bytes,
                    )
                except (
                    ResponseOpenDeadlineError,
                    ResponseReadDeadlineError,
                    TimeoutError,
                ):
                    raise BoundedJsonHttpDeadlineError(
                        "JSON request exceeded its time limit"
                    ) from None
                except (ResponseOpenError, ResponseReadError) as read_error:
                    raise BoundedJsonHttpBodyError(
                        safe_diagnostic_text(
                            str(read_error),
                            sensitive_values=secrets,
                        )
                    ) from None
        finally:
            exc.close()
        raise BoundedJsonHttpStatusError(
            exc.code,
            decode_error_payload(raw, secrets),
        ) from None
    except HttpOpenPolicyError as exc:
        raise BoundedJsonHttpConfigurationError(str(exc)) from None
    except (ResponseOpenDeadlineError, ResponseReadDeadlineError, TimeoutError):
        raise BoundedJsonHttpDeadlineError(
            "JSON request exceeded its time limit"
        ) from None
    except (ResponseOpenError, ResponseReadError) as exc:
        raise BoundedJsonHttpBodyError(
            safe_diagnostic_text(str(exc), sensitive_values=secrets)
        ) from None
    except (
        urllib.error.URLError,
        http.client.HTTPException,
        OSError,
    ):
        raise BoundedJsonHttpNetworkError(
            "JSON request endpoint is unreachable"
        ) from None

    if status < 200 or status >= 300:
        raise BoundedJsonHttpStatusError(
            status,
            decode_error_payload(raw, secrets),
        )
    return BoundedJsonHttpResponse(
        payload=_decode_success_payload(raw),
        status=status,
        headers=headers,
    )


def _read_bounded_body(
    response: Any,
    *,
    deadline: float,
    limit_bytes: int,
) -> bytes:
    declared = _content_length(response)
    if declared is not None and declared > limit_bytes:
        raise BoundedJsonHttpBodyError("JSON response exceeded the size limit")
    try:
        raw = read_response_body(
            response,
            limit_bytes=limit_bytes,
            deadline=deadline,
        )
    except ResponseReadDeadlineError:
        raise
    except ResponseReadError:
        raise
    if len(raw) > limit_bytes:
        raise BoundedJsonHttpBodyError("JSON response exceeded the size limit")
    return raw


def _content_length(response: Any) -> int | None:
    headers = getattr(response, "headers", None)
    get = getattr(headers, "get", None)
    if not callable(get):
        return None
    raw = get("Content-Length")
    try:
        parsed = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _response_status(response: Any) -> int:
    status = getattr(response, "status", None)
    if status is None:
        getcode = getattr(response, "getcode", None)
        status = getcode() if callable(getcode) else 200
    try:
        return int(status)
    except (TypeError, ValueError, OverflowError):
        raise BoundedJsonHttpBodyError(
            "JSON response returned an invalid status"
        ) from None


def _response_headers(response: Any) -> Mapping[str, str]:
    headers = getattr(response, "headers", None)
    items = getattr(headers, "items", None)
    if not callable(items):
        return {}
    try:
        return {str(key).casefold(): str(value) for key, value in items()}
    except (TypeError, ValueError):
        return {}


def _require_final_url(
    request: urllib.request.Request,
    response: Any,
) -> None:
    try:
        require_requested_final_url(request, response)
    except HttpFinalUrlError as exc:
        raise BoundedJsonHttpBodyError(str(exc)) from None


def _decode_success_payload(raw: bytes) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except (RecursionError, UnicodeDecodeError, ValueError) as exc:
        raise BoundedJsonHttpBodyError("JSON response body is not valid JSON") from exc


__all__ = [
    "BoundedJsonHttpBodyError",
    "BoundedJsonHttpConfigurationError",
    "BoundedJsonHttpDeadlineError",
    "BoundedJsonHttpError",
    "BoundedJsonHttpNetworkError",
    "BoundedJsonHttpResponse",
    "BoundedJsonHttpStatusError",
    "error_detail",
    "request_json",
    "safe_diagnostic_text",
]
