"""Validate lifecycle binding on item-attached QA requirements."""

from __future__ import annotations

from typing import Any, MutableMapping, Optional

from yoke_contracts.api.function_call import HandlerOutcome

from yoke_core.domain.handlers.qa import _error
from yoke_core.domain.workflow_runtime import load_item_workflow_runtime


def validate_workflow_transition(
    conn: Any,
    *,
    item_id: int,
    row: MutableMapping[str, Any],
    jsonpath: str,
) -> Optional[HandlerOutcome]:
    """Require a supplied transition to exist in the pinned workflow."""
    raw = row.get("workflow_transition_id")
    if raw is None:
        return None
    transition_id = str(raw).strip()
    if not transition_id:
        return _error(
            "payload_invalid",
            "workflow_transition_id cannot be empty",
            jsonpath=f"{jsonpath}.workflow_transition_id",
        )
    workflow = load_item_workflow_runtime(conn, int(item_id))
    if transition_id not in workflow.stage_ids:
        return _error(
            "payload_invalid",
            f"workflow transition {transition_id!r} is not in "
            f"{workflow.workflow_id}@{workflow.version}",
            jsonpath=f"{jsonpath}.workflow_transition_id",
        )
    row["workflow_transition_id"] = transition_id
    return None


__all__ = ["validate_workflow_transition"]
