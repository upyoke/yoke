"""Authoring and evaluation for ``status:<stage-id>`` satisfactions."""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain.dependency_types import (
    GateResult,
    Satisfaction,
    status_stage_id,
)
from yoke_core.domain.workflow_definition_codec import WorkflowRegistryError
from yoke_core.domain.workflow_runtime import (
    WorkflowRuntime,
    load_item_workflow_runtime,
)

_LEGACY_STATUS = frozenset(
    {
        Satisfaction.STATUS_DONE.value,
        Satisfaction.STATUS_IMPLEMENTED.value,
    }
)


def require_authorable_status_stage(
    conn: Any,
    *,
    blocking_item_id: int,
    satisfaction: str,
) -> None:
    """Refuse a stage missing from the blocker's pinned workflow version."""
    stage_id = status_stage_id(satisfaction)
    if stage_id is None or satisfaction in _LEGACY_STATUS:
        return
    try:
        runtime = load_item_workflow_runtime(conn, int(blocking_item_id))
    except WorkflowRegistryError as exc:
        raise ValueError(f"workflow_pin_unavailable: {exc}") from exc
    if stage_id in runtime.stage_ids:
        return
    available = ", ".join(runtime.stage_ids)
    raise ValueError(
        f"unknown_status_stage: {satisfaction!r} is not a stage in the "
        f"blocking item's pinned workflow {runtime.workflow_id}@"
        f"{runtime.version}; available stages: {available}"
    )


def evaluate_status_satisfaction(
    satisfaction: str,
    blocking_status: str,
    workflow: WorkflowRuntime,
) -> Optional[GateResult]:
    """Evaluate ``status:<stage-id>``, including the two legacy members."""
    stage_id = status_stage_id(satisfaction)
    if stage_id is None:
        return None
    reached = workflow.satisfies_stage_milestone(blocking_status, stage_id)
    if satisfaction == Satisfaction.STATUS_DONE.value:
        if reached:
            return GateResult(True, "Blocking item has reached done.")
        return GateResult(
            False,
            f"Blocking item status is '{blocking_status}'; must reach done.",
        )
    if satisfaction == Satisfaction.STATUS_IMPLEMENTED.value:
        if reached:
            return GateResult(True, "Blocking item has reached implemented or later.")
        return GateResult(
            False,
            f"Blocking item status is '{blocking_status}'; must reach implemented.",
        )
    if reached:
        return GateResult(True, f"Blocking item has reached {stage_id} or later.")
    return GateResult(
        False,
        f"Blocking item status is '{blocking_status}'; must reach {stage_id}.",
    )


__all__ = [
    "evaluate_status_satisfaction",
    "require_authorable_status_stage",
]
