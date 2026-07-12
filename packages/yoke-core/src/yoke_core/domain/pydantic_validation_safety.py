"""Input-free rendering for Pydantic validation failures."""

from __future__ import annotations

from pydantic import ValidationError


def safe_validation_message(
    exc: ValidationError,
    *,
    prefix: str = "payload invalid",
) -> str:
    """Render field paths and reasons without reflecting rejected values."""

    parts: list[str] = []
    for error in exc.errors(include_url=False, include_input=False):
        location = ".".join(str(part) for part in error.get("loc", ())) or "$"
        parts.append(f"{location}: {error.get('msg', 'invalid')}")
    details = "; ".join(parts) or "validation failed"
    return f"{prefix}: {details}"


__all__ = ["safe_validation_message"]
