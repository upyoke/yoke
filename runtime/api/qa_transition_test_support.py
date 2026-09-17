"""Shared workflow transition used by legacy QA fixture families."""

from typing import Any

from yoke_core.domain import qa
from yoke_core.domain.qa_phase_boundary import POST_MERGE_QA_PHASES


QA_GATED_TRANSITION = "reviewed-implementation"
POST_MERGE_TRANSITION = "release"


def _transition_for_phase(qa_phase: Any, explicit: str | None) -> str:
    if explicit:
        return explicit
    phase = str(qa_phase or "verification")
    if phase in POST_MERGE_QA_PHASES:
        return POST_MERGE_TRANSITION
    return QA_GATED_TRANSITION


def add_bound_requirement(**kwargs: Any) -> int:
    """Create fixture QA attached to the phase-appropriate workflow stage."""
    explicit = kwargs.pop("workflow_transition_id", None)
    return qa.cmd_requirement_add(
        workflow_transition_id=_transition_for_phase(
            kwargs.get("qa_phase"), explicit
        ),
        **kwargs,
    )


def bound_requirement_row(**kwargs: Any) -> dict[str, Any]:
    """Build one batch fixture row with its workflow transition."""
    explicit = kwargs.get("workflow_transition_id")
    return {
        **kwargs,
        "workflow_transition_id": _transition_for_phase(
            kwargs.get("qa_phase"), explicit
        ),
    }


__all__ = [
    "QA_GATED_TRANSITION",
    "POST_MERGE_TRANSITION",
    "add_bound_requirement",
    "bound_requirement_row",
]
