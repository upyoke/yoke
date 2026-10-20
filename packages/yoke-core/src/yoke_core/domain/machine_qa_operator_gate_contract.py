"""Closed declarative contract for Machine QA operator gates.

The run performs every step an agent physically can. ``machine_browser_approval``
approves the displayed code in the test machine's already-open browser tab.
``admission_owner_approval`` approves the displayed match code as the
admission fixture's owner with ``yoke machines approve``.
``admission_invite_entry`` issues the fixture owner's invite and types its code
into the terminal. ``human_action`` is the one gate a person finishes: entering
a password or credential the agent may not type. It announces that one step,
sends no input, carries no secret, and only waits for the person to finish it.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any


MACHINE_BROWSER_APPROVAL = "machine_browser_approval"
ADMISSION_OWNER_APPROVAL = "admission_owner_approval"
ADMISSION_INVITE_ENTRY = "admission_invite_entry"
HUMAN_ACTION = "human_action"
PASSWORD_ENTRY = "password_entry"
HUMAN_ACTION_PURPOSES = frozenset({PASSWORD_ENTRY})
AGENT_GATES = frozenset(
    {ADMISSION_INVITE_ENTRY, ADMISSION_OWNER_APPROVAL, MACHINE_BROWSER_APPROVAL}
)
OPERATOR_GATE_FIELDS = frozenset(
    {"completion_text", "gate_timeout_seconds", "human_purpose", "operator_gate"}
)
_GATE_TIMEOUT_MAX_SECONDS = {
    MACHINE_BROWSER_APPROVAL: 600,
    ADMISSION_OWNER_APPROVAL: 600,
    ADMISSION_INVITE_ENTRY: 600,
    HUMAN_ACTION: 1800,
}
MISCLASSIFIED_HUMAN_STEP = (
    "human_action_misclassified: a human gate is only a password or credential "
    "entry the agent may not type (human_purpose password_entry). The run does "
    "every other step itself: use machine_browser_approval to approve a code in "
    "the test machine's signed-in browser, admission_owner_approval to approve "
    "a match code with yoke machines approve, or admission_invite_entry to "
    "issue and type an invite code"
)


def gate_needs_desktop_browser(action: Mapping[str, Any]) -> bool:
    """Return whether this gate's step happens in the test machine's browser."""
    return action.get("operator_gate") == MACHINE_BROWSER_APPROVAL


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
        raise ValueError(MISCLASSIFIED_HUMAN_STEP)
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
    elif operator_gate == MACHINE_BROWSER_APPROVAL:
        if normalized_action["keys"] not in ([], ["Enter"]):
            raise ValueError(
                "machine_browser_approval sends at most Enter before approving"
            )
    elif normalized_action["keys"]:
        raise ValueError(
            f"{operator_gate} types only the input it produces; remove keys"
        )
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
    "ADMISSION_INVITE_ENTRY",
    "ADMISSION_OWNER_APPROVAL",
    "AGENT_GATES",
    "HUMAN_ACTION",
    "HUMAN_ACTION_PURPOSES",
    "MACHINE_BROWSER_APPROVAL",
    "MISCLASSIFIED_HUMAN_STEP",
    "OPERATOR_GATE_FIELDS",
    "PASSWORD_ENTRY",
    "gate_needs_desktop_browser",
    "normalize_operator_gate",
]
