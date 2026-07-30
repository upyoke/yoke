"""Validation for terminal action readiness fields."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any


StringListValidator = Callable[..., list[str]]


def normalize_action_readiness(
    action: Mapping[str, Any],
    *,
    strings: StringListValidator,
) -> dict[str, Any]:
    """Normalize optional readiness text and its bounded timeout."""
    normalized: dict[str, Any] = {}
    if "ready_text" in action:
        normalized["ready_text"] = strings(
            action["ready_text"],
            field="action ready_text",
        )
    if "ready_timeout_seconds" not in action:
        return normalized
    timeout = action["ready_timeout_seconds"]
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or not 0 < float(timeout) <= 300
    ):
        raise ValueError("action ready_timeout_seconds must be numeric from 0..300")
    if "ready_text" not in normalized:
        raise ValueError("action ready_timeout_seconds requires ready_text")
    normalized["ready_timeout_seconds"] = float(timeout)
    return normalized


def registered_terminal_post_check(value: str) -> bool:
    """Return whether a terminal post-check uses the closed vocabulary."""
    if value == "secret_free":
        return True
    if value.startswith("no_text:"):
        return bool(value.removeprefix("no_text:"))
    if value.startswith("terminal_exit_code:"):
        raw_code = value.removeprefix("terminal_exit_code:")
        return raw_code.isdigit() and 0 <= int(raw_code) <= 255
    return False


__all__ = ["normalize_action_readiness", "registered_terminal_post_check"]
