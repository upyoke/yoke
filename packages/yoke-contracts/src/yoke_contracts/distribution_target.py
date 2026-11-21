"""Validate the published release channel and distribution origin."""

from __future__ import annotations

import re
import urllib.parse

_CHANNEL = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


class ReleaseTargetError(RuntimeError):
    """A release cannot be bound to one immutable server image."""


def release_channel(value: str) -> str:
    """Validate an explicit channel without selecting a default."""
    if not _CHANNEL.fullmatch(value):
        raise ReleaseTargetError(
            "invalid release channel; use a published channel name"
        )
    return value


def distribution_base_url(origin: str) -> str:
    """Validate one explicit credential-free distribution origin."""
    selected = str(origin).strip().rstrip("/")
    try:
        parsed = urllib.parse.urlparse(selected)
    except ValueError as exc:
        raise ReleaseTargetError("invalid Yoke distribution origin") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.path not in {"", "/"}
    ):
        raise ReleaseTargetError(
            f"invalid Yoke distribution base URL {selected!r}; set "
            "the distribution origin to an HTTP(S) origin"
        )
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ReleaseTargetError(
            "Yoke distribution base URL must be a credential-free origin"
        )
    return selected
