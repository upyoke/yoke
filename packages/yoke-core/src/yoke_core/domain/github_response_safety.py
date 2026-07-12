"""Shared bounds and redaction for GitHub HTTP response handling."""

from __future__ import annotations

import time
import unicodedata
from collections.abc import Callable
from typing import Any, Iterable

from yoke_cli.transport import response_deadline_read


GITHUB_SMALL_RESPONSE_LIMIT_BYTES = 64 * 1024
GITHUB_COLLECTION_RESPONSE_LIMIT_BYTES = 4 * 1024 * 1024
GITHUB_ERROR_BODY_LIMIT_CHARS = 4 * 1024
GITHUB_DIAGNOSTIC_LIMIT_CHARS = 512
REDACTED_SECRET = "[REDACTED]"
monotonic = time.monotonic


class GitHubResponseSafetyError(ValueError):
    """A GitHub response could not be handled within the safe envelope."""


class GitHubResponseTooLargeError(GitHubResponseSafetyError):
    """A GitHub response exceeded its operation-specific byte limit."""


class GitHubResponseDecodeError(GitHubResponseSafetyError):
    """A GitHub response was not valid UTF-8."""


class GitHubResponseDeadlineError(GitHubResponseSafetyError):
    """A GitHub response body exceeded its absolute deadline."""


def deadline_after(timeout_seconds: float) -> float:
    """Return an absolute monotonic deadline for a positive finite timeout."""
    try:
        return response_deadline_read.deadline_after(
            timeout_seconds,
            clock=monotonic,
        )
    except ValueError as exc:
        raise ValueError("GitHub response timeout must be positive and finite") from exc


def read_bounded_response(
    response: Any,
    *,
    limit_bytes: int,
    label: str,
    deadline: float,
    clock: Callable[[], float] | None = None,
    check_content_length: bool = False,
) -> bytes:
    """Read through one overflow byte without crossing an absolute deadline."""
    if limit_bytes <= 0:
        raise ValueError("GitHub response byte limit must be positive")
    if check_content_length:
        declared = _content_length(response)
        if declared is not None and declared > limit_bytes:
            raise GitHubResponseTooLargeError(
                f"{label} exceeded the response size limit"
            )
    try:
        raw = response_deadline_read.read_response_body(
            response,
            limit_bytes=limit_bytes,
            deadline=deadline,
            clock=clock or monotonic,
        )
    except response_deadline_read.ResponseReadDeadlineError:
        raise GitHubResponseDeadlineError(
            f"{label} exceeded the response time limit"
        ) from None
    except response_deadline_read.ResponseReadError:
        raise GitHubResponseSafetyError(f"{label} did not return bytes") from None
    if len(raw) > limit_bytes:
        raise GitHubResponseTooLargeError(f"{label} exceeded the response size limit")
    return raw


def decode_utf8_response(raw: bytes, *, label: str) -> str:
    """Decode strict UTF-8 into a typed, detail-free failure."""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise GitHubResponseDecodeError(f"{label} was not valid UTF-8") from exc


def redact_exact_secrets(text: str, secrets: Iterable[str]) -> str:
    """Replace every occurrence of each exact non-empty secret value."""
    redacted = str(text)
    selected_secrets = sorted(
        {str(secret or "") for secret in secrets if str(secret or "")},
        key=len,
        reverse=True,
    )
    for secret in selected_secrets:
        redacted = redacted.replace(secret, REDACTED_SECRET)
    return redacted


def safe_diagnostic_text(
    text: str,
    *,
    secrets: Iterable[str] = (),
    maximum_chars: int = GITHUB_DIAGNOSTIC_LIMIT_CHARS,
) -> str:
    """Redact, neutralize terminal controls, flatten, and cap diagnostics."""

    if (
        isinstance(maximum_chars, bool)
        or not isinstance(maximum_chars, int)
        or maximum_chars <= 0
    ):
        raise ValueError("GitHub diagnostic character limit must be positive")
    redacted = redact_exact_secrets(str(text), secrets)
    neutralized = "".join(
        " " if unicodedata.category(character) in {"Cc", "Cf", "Cs"} else character
        for character in redacted
    )
    return " ".join(neutralized.split())[:maximum_chars]


def _content_length(response: Any) -> int | None:
    headers = getattr(response, "headers", None)
    try:
        raw = headers.get("Content-Length") if headers is not None else None
        if raw is None and headers is not None:
            raw = headers.get("content-length")
    except Exception:
        return None
    if raw is None:
        return None
    try:
        parsed = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


__all__ = [
    "GITHUB_COLLECTION_RESPONSE_LIMIT_BYTES",
    "GITHUB_DIAGNOSTIC_LIMIT_CHARS",
    "GITHUB_ERROR_BODY_LIMIT_CHARS",
    "GITHUB_SMALL_RESPONSE_LIMIT_BYTES",
    "GitHubResponseDecodeError",
    "GitHubResponseDeadlineError",
    "GitHubResponseSafetyError",
    "GitHubResponseTooLargeError",
    "REDACTED_SECRET",
    "deadline_after",
    "decode_utf8_response",
    "read_bounded_response",
    "redact_exact_secrets",
    "safe_diagnostic_text",
]
