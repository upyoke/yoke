"""Response bounds and secret scrubbing for the HTTPS function relay."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any, Iterable

from yoke_cli.transport.response_deadline_read import (
    ResponseReadDeadlineError,
    ResponseReadError,
    read_response_body,
)
from yoke_cli.transport.response_limits import DEFAULT_JSON_RESPONSE_LIMIT_BYTES
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionCallResponse,
    FunctionError,
)


FUNCTION_RESPONSE_LIMIT_BYTES = DEFAULT_JSON_RESPONSE_LIMIT_BYTES
REDACTED = "<redacted>"

_SENSITIVE_KEY_WORDS = frozenset(
    {
        "authorization",
        "cookie",
        "credential",
        "credentials",
        "password",
        "passphrase",
        "secret",
        "secrets",
        "token",
        "tokens",
    }
)
_CONTEXT_VALUE_KEYS = frozenset({"content", "data", "plaintext", "value"})
_CONTEXT_NAME_KEYS = frozenset({"field", "key", "name"})
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_NON_WORD = re.compile(r"[^a-z0-9]+")

# Some registered request schemas deliberately use a generic field name for
# sensitive material.  Key-name heuristics cannot classify these values: an
# Actions secret called ``DATABASE_URL`` still travels in ``payload.value``.
# Keep those exceptions bound to the exact function id and payload path so a
# similarly shaped non-secret operation (for example, an Actions variable)
# remains visible in ordinary responses.
_SENSITIVE_PAYLOAD_PATHS_BY_FUNCTION: Mapping[str, tuple[tuple[str, ...], ...]] = {
    "github_actions.secret.set": (("value",),),
}

# These exact request fields are public by contract even when one nested key
# contains a word such as ``credentials``. Pack render values are non-secret
# project settings and are echoed into the checksum-protected source bundle;
# treating an action pin as a secret would rewrite the response content after
# the server calculated its digest.
_PUBLIC_PAYLOAD_FIELDS_BY_FUNCTION: Mapping[str, frozenset[str]] = {
    "packs.bundle.get": frozenset({"render_values"}),
}


class HttpsResponsePolicyError(ValueError):
    """One remote response cannot safely become a typed envelope."""


def read_bounded_response(
    response: Any,
    *,
    deadline: float,
    limit_bytes: int = FUNCTION_RESPONSE_LIMIT_BYTES,
) -> bytes:
    """Read one body with size preflight, deadline, and overflow sentinel."""

    declared_length = _content_length(response)
    if declared_length is not None and declared_length > limit_bytes:
        raise HttpsResponsePolicyError(
            "HTTPS function relay response exceeded the size limit"
        )
    try:
        raw = read_response_body(
            response,
            limit_bytes=limit_bytes,
            deadline=deadline,
        )
    except ResponseReadDeadlineError:
        raise HttpsResponsePolicyError(
            "HTTPS function relay response exceeded the time limit"
        ) from None
    except ResponseReadError:
        raise HttpsResponsePolicyError(
            "HTTPS function relay returned a malformed response"
        ) from None
    if len(raw) > limit_bytes:
        raise HttpsResponsePolicyError(
            "HTTPS function relay response exceeded the size limit"
        )
    return bytes(raw)


def collect_request_secrets(
    request: FunctionCallRequest,
    *,
    transport_token: str = "",
) -> tuple[str, ...]:
    """Collect string secrets from nested request fields by key semantics."""

    found: set[str] = set()
    document = request.model_dump(mode="json")
    payload = document.get("payload")
    public_fields = _PUBLIC_PAYLOAD_FIELDS_BY_FUNCTION.get(request.function, ())
    if isinstance(payload, Mapping) and public_fields:
        document["payload"] = {
            key: value for key, value in payload.items() if key not in public_fields
        }
    _collect_nested(
        document,
        found,
        inherited_sensitive=False,
    )
    _collect_declared_payload_secrets(request.function, request.payload, found)
    if transport_token:
        found.add(transport_token)
    return tuple(sorted(found, key=lambda value: (-len(value), value)))


def parse_typed_response(
    raw: bytes,
    *,
    sensitive_values: Iterable[str],
) -> FunctionCallResponse:
    """Strictly decode, scrub, and validate one response envelope."""

    scrubbed = _decode_and_redact(raw, sensitive_values)
    try:
        return FunctionCallResponse.model_validate(scrubbed)
    except (RecursionError, TypeError, ValueError) as exc:
        raise HttpsResponsePolicyError(
            "HTTPS function relay returned a malformed typed envelope"
        ) from exc


def adopt_boundary_error(
    request: FunctionCallRequest,
    raw: bytes,
    *,
    sensitive_values: Iterable[str],
) -> FunctionCallResponse | None:
    """Adopt the shorter pre-dispatch denial shape into the full envelope."""

    try:
        payload = _decode_and_redact(raw, sensitive_values)
    except HttpsResponsePolicyError:
        return None
    if not isinstance(payload, dict) or payload.get("success") is not False:
        return None
    error = payload.get("error")
    if not isinstance(error, dict) or not error.get("code"):
        return None
    try:
        return FunctionCallResponse(
            success=False,
            function=request.function,
            version=request.version,
            request_id=request.request_id,
            error=FunctionError(
                code=str(error.get("code")),
                message=str(error.get("message") or ""),
                jsonpath=error.get("jsonpath"),
                recovery_hint=error.get("recovery_hint"),
            ),
        )
    except (RecursionError, TypeError, ValueError):
        return None


def safe_excerpt(
    raw: bytes,
    *,
    sensitive_values: Iterable[str],
    limit_chars: int = 200,
) -> str:
    """Return a strict-UTF-8, scrubbed excerpt for a non-envelope body."""

    try:
        value = raw.decode("utf-8").strip()
    except UnicodeDecodeError:
        return ""
    try:
        json.loads(value)
    except ValueError:
        pass
    else:
        return ""
    return redact_text(value, sensitive_values)[:limit_chars]


def redact_nested(value: Any, sensitive_values: Iterable[str]) -> Any:
    """Recursively scrub secret occurrences from JSON-shaped data."""

    secrets = tuple(sensitive_values)
    if isinstance(value, str):
        return redact_text(value, secrets)
    if isinstance(value, Mapping):
        return {
            redact_text(str(key), secrets): redact_nested(item, secrets)
            for key, item in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [redact_nested(item, secrets) for item in value]
    return value


def redact_text(value: str, sensitive_values: Iterable[str]) -> str:
    """Replace literal and JSON-escaped forms of every sensitive value."""

    scrubbed = value
    needles = _redaction_needles(sensitive_values)
    for needle in needles:
        scrubbed = scrubbed.replace(needle, REDACTED)
    return scrubbed


def _decode_json(raw: bytes) -> Any:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HttpsResponsePolicyError(
            "HTTPS function relay response was not valid UTF-8"
        ) from exc
    try:
        return json.loads(text)
    except RecursionError as exc:
        raise HttpsResponsePolicyError(
            "HTTPS function relay response exceeded the nesting limit"
        ) from exc
    except ValueError as exc:
        raise HttpsResponsePolicyError(
            "HTTPS function relay response was not valid JSON"
        ) from exc


def _decode_and_redact(raw: bytes, sensitive_values: Iterable[str]) -> Any:
    try:
        return redact_nested(_decode_json(raw), sensitive_values)
    except RecursionError as exc:
        raise HttpsResponsePolicyError(
            "HTTPS function relay response exceeded the nesting limit"
        ) from exc


def _content_length(response: Any) -> int | None:
    headers = getattr(response, "headers", None)
    get = getattr(headers, "get", None)
    if not callable(get):
        return None
    value = get("Content-Length")
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _collect_nested(
    value: Any,
    found: set[str],
    *,
    inherited_sensitive: bool,
) -> None:
    if isinstance(value, str):
        if inherited_sensitive and value:
            found.add(value)
        return
    if isinstance(value, Mapping):
        context_secret = _mapping_names_sensitive_value(value)
        for key, item in value.items():
            normalized_key = _normalize_key(str(key))
            sensitive = inherited_sensitive or _is_sensitive_key(normalized_key)
            if context_secret and normalized_key in _CONTEXT_VALUE_KEYS:
                sensitive = True
            _collect_nested(item, found, inherited_sensitive=sensitive)
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            _collect_nested(
                item,
                found,
                inherited_sensitive=inherited_sensitive,
            )


def _collect_declared_payload_secrets(
    function_id: str,
    payload: Mapping[str, Any],
    found: set[str],
) -> None:
    """Collect secrets declared by one registered function's request shape."""

    for path in _SENSITIVE_PAYLOAD_PATHS_BY_FUNCTION.get(function_id, ()):
        value: Any = payload
        for segment in path:
            if not isinstance(value, Mapping) or segment not in value:
                break
            value = value[segment]
        else:
            if isinstance(value, str) and value:
                found.add(value)


def _mapping_names_sensitive_value(value: Mapping[Any, Any]) -> bool:
    return any(
        _normalize_key(str(key)) in _CONTEXT_NAME_KEYS
        and isinstance(item, str)
        and _is_sensitive_key(_normalize_key(item))
        for key, item in value.items()
    )


def _normalize_key(value: str) -> str:
    with_boundaries = _CAMEL_BOUNDARY.sub("_", value)
    return _NON_WORD.sub("_", with_boundaries.lower()).strip("_")


def _is_sensitive_key(normalized_key: str) -> bool:
    words = frozenset(normalized_key.split("_"))
    if words & _SENSITIVE_KEY_WORDS:
        return True
    return "key" in words and bool(words & {"access", "api", "private", "signing"})


def _redaction_needles(values: Iterable[str]) -> tuple[str, ...]:
    needles: set[str] = set()
    for value in values:
        if not value:
            continue
        needles.add(value)
        needles.add(json.dumps(value, ensure_ascii=True)[1:-1])
        needles.add(json.dumps(value, ensure_ascii=False)[1:-1])
    needles.discard("")
    return tuple(sorted(needles, key=lambda item: (-len(item), item)))


__all__ = [
    "FUNCTION_RESPONSE_LIMIT_BYTES",
    "HttpsResponsePolicyError",
    "REDACTED",
    "adopt_boundary_error",
    "collect_request_secrets",
    "parse_typed_response",
    "read_bounded_response",
    "redact_nested",
    "redact_text",
    "safe_excerpt",
]
