"""Shared bounds and redaction for GitHub HTTP response handling."""

from __future__ import annotations

from typing import Any, Iterable


GITHUB_SMALL_RESPONSE_LIMIT_BYTES = 64 * 1024
GITHUB_COLLECTION_RESPONSE_LIMIT_BYTES = 4 * 1024 * 1024
REDACTED_SECRET = "[REDACTED]"


class GitHubResponseSafetyError(ValueError):
    """A GitHub response could not be handled within the safe envelope."""


class GitHubResponseTooLargeError(GitHubResponseSafetyError):
    """A GitHub response exceeded its operation-specific byte limit."""


class GitHubResponseDecodeError(GitHubResponseSafetyError):
    """A GitHub response was not valid UTF-8."""


def read_bounded_response(
    response: Any,
    *,
    limit_bytes: int,
    label: str,
    check_content_length: bool = False,
) -> bytes:
    """Read at most one overflow sentinel beyond ``limit_bytes``."""
    if limit_bytes <= 0:
        raise ValueError("GitHub response byte limit must be positive")
    if check_content_length:
        declared = _content_length(response)
        if declared is not None and declared > limit_bytes:
            raise GitHubResponseTooLargeError(
                f"{label} exceeded the response size limit"
            )
    raw = response.read(limit_bytes + 1)
    if not isinstance(raw, (bytes, bytearray, memoryview)):
        raise GitHubResponseSafetyError(f"{label} did not return bytes")
    if len(raw) > limit_bytes:
        raise GitHubResponseTooLargeError(f"{label} exceeded the response size limit")
    return bytes(raw)


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
    "GITHUB_SMALL_RESPONSE_LIMIT_BYTES",
    "GitHubResponseDecodeError",
    "GitHubResponseSafetyError",
    "GitHubResponseTooLargeError",
    "REDACTED_SECRET",
    "decode_utf8_response",
    "read_bounded_response",
    "redact_exact_secrets",
]
