"""Compose operator-facing refusals with a reachable recovery.

Reason and recovery are two obligations. A message that names only the
condition it tripped on is unfinished: the reader assumes anything
unreported is fine, and a listed remedy this caller's state forbids is a
defect. Authors format refusals through :func:`compose_refusal`; reviewers
check the same helper and the teaching in ``code-and-cli.md``.
"""

from __future__ import annotations

from collections.abc import Sequence


def compose_refusal(
    reason: str,
    *,
    recovery: str | None = None,
    evaluated: str | None = None,
    unavailable: Sequence[str] = (),
    escalate_to: str | None = None,
) -> str:
    """Format a refusal: reason, whole evaluated state, reachable next step.

    ``recovery`` is the action this caller's own state can actually take.
    When none is reachable, omit it and pass ``escalate_to``. ``evaluated``
    is the whole state inspected, not only the failing part.
    ``unavailable`` names remedies that look relevant but this state forbids.
    """
    reason_text = str(reason or "").strip()
    if not reason_text:
        raise ValueError("refusal reason is required")
    recovery_text = str(recovery or "").strip()
    escalate_text = str(escalate_to or "").strip()
    if recovery_text and escalate_text:
        raise ValueError("pass recovery or escalate_to, not both")
    if not recovery_text and not escalate_text:
        raise ValueError(
            "a refusal with no reachable recovery must name who to escalate to"
        )
    parts = [reason_text.rstrip(".")]
    evaluated_text = str(evaluated or "").strip()
    if evaluated_text:
        parts.append(f"Evaluated: {evaluated_text.rstrip('.')}")
    blocked = [str(item).strip().rstrip(".") for item in unavailable if str(item).strip()]
    if blocked:
        parts.append("Not available: " + "; ".join(blocked))
    if recovery_text:
        parts.append(f"Recovery: {recovery_text.rstrip('.')}")
    else:
        parts.append(
            f"No reachable recovery from this call; escalate to {escalate_text}"
        )
    return ". ".join(parts) + "."


__all__ = ["compose_refusal"]
