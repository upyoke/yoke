"""Shared workflow transition used by legacy QA fixture families."""

from typing import Any

from yoke_core.domain import qa


QA_GATED_TRANSITION = "reviewed-implementation"


def add_bound_requirement(**kwargs: Any) -> int:
    """Create fixture QA attached to the shared QA-gated transition."""
    return qa.cmd_requirement_add(
        workflow_transition_id=QA_GATED_TRANSITION,
        **kwargs,
    )


def bound_requirement_row(**kwargs: Any) -> dict[str, Any]:
    """Build one batch fixture row with its workflow transition."""
    return {
        **kwargs,
        "workflow_transition_id": QA_GATED_TRANSITION,
    }


__all__ = [
    "QA_GATED_TRANSITION",
    "add_bound_requirement",
    "bound_requirement_row",
]
