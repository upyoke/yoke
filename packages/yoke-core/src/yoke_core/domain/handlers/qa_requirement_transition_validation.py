"""Validate lifecycle binding on item-attached QA requirements."""

from __future__ import annotations

from typing import Any, MutableMapping, Optional

from yoke_contracts.api.function_call import HandlerOutcome

from yoke_core.domain.handlers.qa import _error
from yoke_core.domain.qa_workflow_binding_validation import (
    QaWorkflowBindingError,
    validate_item_qa_transition,
)
from yoke_core.domain.workflow_registry import WorkflowRegistryError


def validate_workflow_transition(
    conn: Any,
    *,
    item_id: int,
    row: MutableMapping[str, Any],
    jsonpath: str,
) -> Optional[HandlerOutcome]:
    """Require an item QA transition with a gate in the pinned workflow."""
    try:
        transition_id, _workflow = validate_item_qa_transition(
            conn,
            item_id=int(item_id),
            transition_id=row.get("workflow_transition_id"),
        )
    except (QaWorkflowBindingError, WorkflowRegistryError) as exc:
        return _error(
            "payload_invalid",
            str(exc),
            jsonpath=f"{jsonpath}.workflow_transition_id",
        )
    row["workflow_transition_id"] = transition_id
    return None


__all__ = ["validate_workflow_transition"]
