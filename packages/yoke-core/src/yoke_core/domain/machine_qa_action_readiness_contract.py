"""Validation for terminal action readiness fields."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any


StringListValidator = Callable[..., list[str]]

READY_TIMEOUT_MAX_SECONDS = 300.0


def bound_ready_timeout_seconds(timeout: object) -> float:
    """Return a ready timeout inside the shared authoring/execution bound."""
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or not 0 < float(timeout) <= READY_TIMEOUT_MAX_SECONDS
    ):
        raise ValueError(
            "action ready_timeout_seconds must be numeric from "
            f"0..{int(READY_TIMEOUT_MAX_SECONDS)}"
        )
    return float(timeout)


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
    timeout = bound_ready_timeout_seconds(action["ready_timeout_seconds"])
    if "ready_text" not in normalized:
        raise ValueError("action ready_timeout_seconds requires ready_text")
    normalized["ready_timeout_seconds"] = timeout
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


__all__ = [
    "READY_TIMEOUT_MAX_SECONDS",
    "bound_ready_timeout_seconds",
    "normalize_action_readiness",
    "registered_terminal_post_check",
]
