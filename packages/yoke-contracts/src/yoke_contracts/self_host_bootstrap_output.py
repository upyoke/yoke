"""Dependency-light contract for a self-host server's first-boot output."""

from __future__ import annotations

import re


TOKEN_PREFIX = "yoke_v1_"
TOKEN_BODY_LENGTH = 43
FIRST_BOOT_TOKEN_MARKER = "FIRST-BOOT ADMIN TOKEN"

_TOKEN_PATTERN = re.compile(
    rf"(?<![A-Za-z0-9_]){re.escape(TOKEN_PREFIX)}"
    rf"[A-Za-z0-9]{{{TOKEN_BODY_LENGTH}}}(?![A-Za-z0-9])"
)
_BOOT_OUTPUT_WINDOW = 2048


def is_api_token(value: str) -> bool:
    """Return whether ``value`` has the public Yoke API-token wire shape."""
    return _TOKEN_PATTERN.fullmatch(str(value or "")) is not None


def first_boot_admin_token_block(raw_token: str) -> str:
    """Render the one-time first-admin credential block printed at boot."""
    if not is_api_token(raw_token):
        raise ValueError("first-boot admin token has an invalid wire shape")
    border = "=" * 64
    return "\n".join(
        (
            border,
            f"  {FIRST_BOOT_TOKEN_MARKER} — shown once, never stored, never reprinted",
            "",
            f"      {raw_token}",
            "",
            "  Save it now, then connect a client to this server with:",
            "      yoke connect <server-url>",
            border,
        )
    )


def extract_first_boot_admin_token(output: str) -> str | None:
    """Extract the token from bounded plain or Compose-prefixed boot logs.

    Only text following the last marker is inspected. This prevents an
    unrelated token elsewhere in diagnostic output from being adopted as the
    server's first-admin credential.
    """
    text = str(output or "")
    marker_at = text.rfind(FIRST_BOOT_TOKEN_MARKER)
    if marker_at < 0:
        return None
    window = text[marker_at : marker_at + _BOOT_OUTPUT_WINDOW]
    matches = tuple(dict.fromkeys(_TOKEN_PATTERN.findall(window)))
    return matches[0] if len(matches) == 1 else None


def redact_api_tokens(value: str) -> str:
    """Remove raw Yoke API tokens from diagnostics and error messages."""
    return _TOKEN_PATTERN.sub("[Yoke API token redacted]", str(value or ""))


__all__ = [
    "FIRST_BOOT_TOKEN_MARKER",
    "TOKEN_BODY_LENGTH",
    "TOKEN_PREFIX",
    "extract_first_boot_admin_token",
    "first_boot_admin_token_block",
    "is_api_token",
    "redact_api_tokens",
]
