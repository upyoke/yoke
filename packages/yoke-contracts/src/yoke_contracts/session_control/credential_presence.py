"""Safe boolean-only machine credential-presence projection."""

from __future__ import annotations

from typing import Any, Mapping


HARNESSES = ("claude-cli", "codex-cli", "cursor-cli")


def sanitize_credential_presence(raw: Any) -> dict[str, Any]:
    document = raw if isinstance(raw, Mapping) else {}
    harnesses = document.get("harnesses")
    harnesses = harnesses if isinstance(harnesses, Mapping) else {}
    return {
        "github": document.get("github") is True,
        "aws": document.get("aws") is True,
        "harnesses": {surface: harnesses.get(surface) is True for surface in HARNESSES},
    }


__all__ = ["HARNESSES", "sanitize_credential_presence"]
