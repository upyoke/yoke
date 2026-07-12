"""Secret-safe rendering for untrusted GitHub response diagnostics."""

from __future__ import annotations

import time
from typing import Any, Callable, Iterable
import unicodedata


MAX_GITHUB_ERROR_TEXT_CHARS = 500
GITHUB_RESPONSE_READ_CHUNK_BYTES = 16 * 1024
SAFE_GITHUB_OAUTH_ERROR_CODES = frozenset({
    "access_denied",
    "authorization_pending",
    "device_flow_disabled",
    "expired_token",
    "incorrect_client_credentials",
    "incorrect_device_code",
    "slow_down",
    "unsupported_grant_type",
})


class GitHubResponseReadError(RuntimeError):
    """An untrusted response exceeded its byte or wall-clock boundary."""


def read_bounded(
    response: Any,
    *,
    maximum_bytes: int,
    deadline: float,
    monotonic: Callable[[], float] | None = None,
) -> bytes:
    """Read one response under an absolute deadline and a byte ceiling."""
    clock = monotonic or time.monotonic
    read1 = getattr(response, "read1", None)
    if not callable(read1):
        _set_read_timeout(response, _remaining(deadline, clock))
        payload = response.read(maximum_bytes + 1)
        _remaining(deadline, clock)
        return _validate_payload(payload, maximum_bytes)

    chunks: list[bytes] = []
    size = 0
    while True:
        _set_read_timeout(response, _remaining(deadline, clock))
        chunk = read1(GITHUB_RESPONSE_READ_CHUNK_BYTES)
        _remaining(deadline, clock)
        if not chunk:
            break
        if not isinstance(chunk, bytes):
            raise GitHubResponseReadError("GitHub response body is not bytes")
        chunks.append(chunk)
        size += len(chunk)
        if size > maximum_bytes:
            raise GitHubResponseReadError("GitHub response body is too large")
    return b"".join(chunks)


def _remaining(deadline: float, monotonic: Callable[[], float]) -> float:
    remaining = deadline - monotonic()
    if remaining <= 0:
        raise GitHubResponseReadError("GitHub response exceeded its deadline")
    return remaining


def _validate_payload(payload: Any, maximum_bytes: int) -> bytes:
    if not isinstance(payload, bytes):
        raise GitHubResponseReadError("GitHub response body is not bytes")
    if len(payload) > maximum_bytes:
        raise GitHubResponseReadError("GitHub response body is too large")
    return payload


def _set_read_timeout(response: Any, seconds: float) -> None:
    """Tighten the underlying urllib socket timeout when it is reachable."""
    queue = [response]
    visited: set[int] = set()
    while queue:
        current = queue.pop(0)
        if id(current) in visited:
            continue
        visited.add(id(current))
        setter = getattr(current, "settimeout", None)
        if callable(setter):
            try:
                setter(seconds)
                return
            except (OSError, TypeError, ValueError):
                pass
        for attribute in ("fp", "raw", "_sock", "sock", "socket"):
            nested = getattr(current, attribute, None)
            if nested is not None:
                queue.append(nested)


def safe_error_text(
    value: Any,
    *,
    secrets: Iterable[str] = (),
) -> str:
    """Normalize, redact known secrets, and cap one hostile error string."""
    rendered = str(value or "")
    for secret in secrets:
        selected = str(secret or "")
        if selected:
            rendered = rendered.replace(selected, "<redacted>")
    return terminal_safe_text(
        rendered, maximum_chars=MAX_GITHUB_ERROR_TEXT_CHARS,
    )


def terminal_safe_text(value: Any, *, maximum_chars: int) -> str:
    """Flatten hostile text after neutralizing terminal control characters."""

    raw = str(value or "")
    without_controls = "".join(
        " " if unicodedata.category(char) in {"Cc", "Cf"} else char
        for char in raw
    )
    return " ".join(without_controls.split())[:maximum_chars]


def safe_oauth_error_code(
    value: Any,
    *,
    secrets: Iterable[str] = (),
) -> str:
    """Return a documented OAuth code or one generic non-echoing label."""
    rendered = safe_error_text(value, secrets=secrets)
    return rendered if rendered in SAFE_GITHUB_OAUTH_ERROR_CODES else "oauth_error"


__all__ = [
    "GITHUB_RESPONSE_READ_CHUNK_BYTES",
    "GitHubResponseReadError",
    "MAX_GITHUB_ERROR_TEXT_CHARS",
    "SAFE_GITHUB_OAUTH_ERROR_CODES",
    "read_bounded",
    "safe_error_text",
    "safe_oauth_error_code",
    "terminal_safe_text",
]
