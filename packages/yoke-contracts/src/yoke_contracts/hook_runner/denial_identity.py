"""Shared rendering for the check id carried by a hook denial."""

from __future__ import annotations


CHECK_ID_PREFIX = "Yoke check id: "


def check_id_line(check_id: str) -> str:
    """Return the required human-facing identity line for *check_id*."""
    value = check_id.strip()
    if not value:
        raise ValueError("a hook denial check id cannot be empty")
    return f"{CHECK_ID_PREFIX}{value}"


def attach_check_id(reason: str, check_id: str) -> str:
    """Attach exactly one current check-id line without hiding recovery text."""
    line = check_id_line(check_id)
    trailing_newline = reason.endswith("\n")
    stripped = reason.rstrip("\n")
    kept = [
        part for part in stripped.splitlines() if not part.startswith(CHECK_ID_PREFIX)
    ]
    body = "\n".join(kept).rstrip("\n")
    rendered = f"{body}\n\n{line}"
    return f"{rendered}\n" if trailing_newline else rendered


__all__ = ["CHECK_ID_PREFIX", "attach_check_id", "check_id_line"]
