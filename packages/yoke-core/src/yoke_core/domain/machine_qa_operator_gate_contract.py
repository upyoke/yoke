"""Closed declarative contract for Machine QA operator gates.

``machine_browser_approval`` is the dedicated-machine exception: the run's
browser helper approves the displayed code itself. ``human_action`` is the
non-self-approving gate: the run announces one typed human step, sends no
input, carries no secret, and only waits for the person to finish it.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any


MACHINE_BROWSER_APPROVAL = "machine_browser_approval"
HUMAN_ACTION = "human_action"
HUMAN_ACTION_PURPOSES = frozenset(
    {"company_sign_in", "machine_approval", "private_invite_entry"}
)
OPERATOR_GATE_FIELDS = frozenset(
    {"completion_text", "gate_timeout_seconds", "human_purpose", "operator_gate"}
)
_GATE_TIMEOUT_MAX_SECONDS = {MACHINE_BROWSER_APPROVAL: 600, HUMAN_ACTION: 1800}


def gate_needs_desktop_browser(action: Mapping[str, Any]) -> bool:
    """Return whether this gate's step happens in the test machine's browser."""
    gate = action.get("operator_gate")
    return gate == MACHINE_BROWSER_APPROVAL or (
        gate == HUMAN_ACTION and action.get("human_purpose") == "company_sign_in"
    )


def _normalize_human_action(
    action: Mapping[str, Any],
    normalized_action: dict[str, Any],
) -> None:
    if normalized_action["keys"]:
        raise ValueError(
            "human_action never sends input; remove keys so the person types "
            "privately on the test machine"
        )
    if "ready_text" in normalized_action:
        raise ValueError(
            "human_action reads its context from the preceding step; move "
            "ready_text to that step"
        )
    purpose = action.get("human_purpose")
    if purpose not in HUMAN_ACTION_PURPOSES:
        raise ValueError(
            f"human_action human_purpose must be one of {sorted(HUMAN_ACTION_PURPOSES)}"
        )
    normalized_action["human_purpose"] = purpose


def normalize_operator_gate(
    action: Mapping[str, Any],
    normalized_action: dict[str, Any],
    *,
    strings: Callable[..., list[str]],
) -> None:
    """Validate and append one registered operator gate in place."""
    step = str(normalized_action["step"])
    operator_gate = action.get("operator_gate")
    if operator_gate is None:
        if "operator" in step.casefold() and "wait_seconds" in normalized_action:
            raise ValueError("operator actions must use a typed gate, not wait_seconds")
        if OPERATOR_GATE_FIELDS & set(action):
            raise ValueError(
                "completion_text, gate_timeout_seconds and human_purpose "
                "require operator_gate"
            )
        return
    if operator_gate not in _GATE_TIMEOUT_MAX_SECONDS:
        raise ValueError("action operator_gate is not registered")
    if "wait_seconds" in normalized_action:
        raise ValueError("operator actions must use a typed gate, not wait_seconds")
    if operator_gate == HUMAN_ACTION:
        _normalize_human_action(action, normalized_action)
    elif "human_purpose" in action:
        raise ValueError("human_purpose belongs only to the human_action gate")
    elif normalized_action["keys"] != ["Enter"]:
        raise ValueError("machine_browser_approval must immediately send Enter")
    completion_text = strings(
        action.get("completion_text"),
        field="action completion_text",
    )
    maximum = _GATE_TIMEOUT_MAX_SECONDS[operator_gate]
    gate_timeout = action.get("gate_timeout_seconds")
    if (
        isinstance(gate_timeout, bool)
        or not isinstance(gate_timeout, (int, float))
        or not 1 <= float(gate_timeout) <= maximum
    ):
        raise ValueError(
            f"action gate_timeout_seconds must be numeric from 1..{maximum}"
        )
    normalized_action.update(
        {
            "operator_gate": operator_gate,
            "completion_text": completion_text,
            "gate_timeout_seconds": float(gate_timeout),
        }
    )


__all__ = [
    "HUMAN_ACTION",
    "HUMAN_ACTION_PURPOSES",
    "MACHINE_BROWSER_APPROVAL",
    "OPERATOR_GATE_FIELDS",
    "gate_needs_desktop_browser",
    "normalize_operator_gate",
]
