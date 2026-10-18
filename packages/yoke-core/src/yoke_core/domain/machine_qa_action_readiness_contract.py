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


def require_keyed_ready_text(action: Mapping[str, Any]) -> None:
    """Refuse a step that sends keys without naming the screen it answers.

    A prompt that never appears then fails that step by name instead of being
    typed into blindly. The browser-approval gate reads its own approval
    context, so it is exempt.
    """
    if (
        action.get("keys")
        and not action.get("operator_gate")
        and not action.get("ready_text")
    ):
        raise ValueError(
            f"action {action.get('step')!r} sends keys without ready_text; "
            "name the prompt text that step answers, or remove the step when "
            "the installer no longer shows that prompt"
        )


def normalize_action_readiness(
    action: Mapping[str, Any],
    *,
    strings: StringListValidator,
) -> dict[str, Any]:
    """Normalize readiness text and its bounded timeout.

    Every keyed step must name its ready text; see ``require_keyed_ready_text``.
    """
    normalized: dict[str, Any] = {}
    if "ready_text" in action:
        normalized["ready_text"] = strings(
            action["ready_text"],
            field="action ready_text",
        )
    require_keyed_ready_text(action)
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
    "require_keyed_ready_text",
    "registered_terminal_post_check",
]
