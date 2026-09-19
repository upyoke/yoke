"""Rebind one item QA requirement to a different lifecycle stage.

Split from :mod:`qa_requirement_config_update`, which owns the update
dispatch. This is the lifecycle-binding field, and it exists because
``post_merge_binding_refusal`` refuses a post-merge phase at a pre-release
stage only at creation: rows recorded before that refusal existed still
carry ``qa_phase='post_deploy'`` against a pre-merge transition, which is a
binding no surface would produce today and none can act on. Rebinding them
to the release wait is the correction the refusal itself names.

The new binding is validated exactly as a fresh attachment is, through
``validate_item_qa_transition``, so a rebind can only ever land somewhere a
create could have.
"""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain.qa_workflow_binding_validation import (
    QaWorkflowBindingError,
    validate_item_qa_transition,
)
from yoke_core.domain.workflow_registry import WorkflowRegistryError


def _prepare_workflow_transition(
    conn: Any, existing: Any, value: Any
) -> tuple[Optional[str], str]:
    """Validate a replacement lifecycle binding, or name why it refuses."""
    if existing["deployment_run_id"]:
        return None, (
            "workflow_transition_id binds item QA to a lifecycle stage; a "
            "deployment-run requirement is bound to its run's stage instead"
        )
    item_id = existing["item_id"]
    if item_id is None:
        return None, (
            "workflow_transition_id is updatable only on an item-attached "
            "requirement"
        )
    try:
        transition, _workflow = validate_item_qa_transition(
            conn,
            item_id=int(item_id),
            transition_id=value,
            plan_id=existing["plan_id"],
            method_id=existing["method_id"],
            qa_phase=existing["qa_phase"],
        )
    except (QaWorkflowBindingError, WorkflowRegistryError) as exc:
        return None, str(exc)
    return transition, ""


__all__ = ["_prepare_workflow_transition"]
