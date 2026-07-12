"""Secret and terminal-control safety for hosted JSON diagnostics."""

from __future__ import annotations

import json
import unicodedata
import urllib.request
from collections.abc import Iterable, Mapping, Sequence
from typing import Any


DIAGNOSTIC_LIMIT_CHARS = 512


def safe_diagnostic_text(
    value: Any,
    *,
    sensitive_values: Iterable[str] = (),
    limit_chars: int = DIAGNOSTIC_LIMIT_CHARS,
) -> str:
    """Return one redacted, control-escaped, length-bounded diagnostic."""

    if isinstance(limit_chars, bool) or not isinstance(limit_chars, int):
        raise ValueError("diagnostic character limit must be a positive integer")
    if limit_chars <= 0:
        raise ValueError("diagnostic character limit must be a positive integer")
    scrubbed = str(value)
    needles = sorted(
        {str(item) for item in sensitive_values if str(item)},
        key=lambda item: (-len(item), item),
    )
    for needle in needles:
        scrubbed = scrubbed.replace(needle, "<redacted>")
        escaped = json.dumps(needle, ensure_ascii=True)[1:-1]
        if escaped:
            scrubbed = scrubbed.replace(escaped, "<redacted>")
    safe = "".join(_safe_diagnostic_character(char) for char in scrubbed)
    if len(safe) <= limit_chars:
        return safe
    return safe[: max(0, limit_chars - 3)] + "..."


def error_detail(payload: Any) -> str:
    """Extract one already-scrubbed message from a status payload."""

    if not isinstance(payload, Mapping):
        return ""
    error = payload.get("error")
    if isinstance(error, Mapping):
        message = error.get("message")
        if isinstance(message, str):
            return message
    detail = payload.get("detail")
    return detail if isinstance(detail, str) else ""


def decode_error_payload(raw: bytes, sensitive_values: tuple[str, ...]) -> Any:
    """Decode one error object while redacting secrets and terminal controls."""

    if not raw:
        return None
    try:
        payload = json.loads(raw.decode("utf-8"))
        return _sanitize_payload(payload, sensitive_values, depth=0)
    except (RecursionError, UnicodeDecodeError, ValueError):
        return None


def request_secrets(
    request: urllib.request.Request,
    sensitive_values: Iterable[str],
) -> tuple[str, ...]:
    """Combine declared secrets with the request's bearer credential."""

    values = {str(value) for value in sensitive_values if str(value)}
    authorization = request.get_header("Authorization") or ""
    if authorization:
        values.add(authorization)
        prefix, separator, credential = authorization.partition(" ")
        if separator and prefix.casefold() == "bearer" and credential:
            values.add(credential)
    return tuple(sorted(values, key=lambda item: (-len(item), item)))


def _sanitize_payload(value: Any, secrets: tuple[str, ...], *, depth: int) -> Any:
    if depth >= 64:
        return "<truncated>"
    if isinstance(value, str):
        return safe_diagnostic_text(value, sensitive_values=secrets)
    if isinstance(value, Mapping):
        return {
            safe_diagnostic_text(key, sensitive_values=secrets): _sanitize_payload(
                item,
                secrets,
                depth=depth + 1,
            )
            for key, item in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_sanitize_payload(item, secrets, depth=depth + 1) for item in value]
    return value


def _safe_diagnostic_character(char: str) -> str:
    codepoint = ord(char)
    if char in {"\n", "\r", "\t"} or unicodedata.category(char).startswith("C"):
        if codepoint <= 0xFF:
            return f"\\x{codepoint:02x}"
        if codepoint <= 0xFFFF:
            return f"\\u{codepoint:04x}"
        return f"\\U{codepoint:08x}"
    return char


__all__ = [
    "DIAGNOSTIC_LIMIT_CHARS",
    "decode_error_payload",
    "error_detail",
    "request_secrets",
    "safe_diagnostic_text",
]
