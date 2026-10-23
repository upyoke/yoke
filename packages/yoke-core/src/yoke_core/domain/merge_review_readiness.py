"""Review readiness at the standalone merge boundary.

`yoke merge item` lands a branch and, unless ``--skip-status`` is passed,
closes the item out afterwards. Neither half may land work the item's own
workflow has not reviewed: admission asks whether the item has reached the
stage its workflow declares for review.

An item one declared edge before that stage is not refused. The merge
performs that transition itself, after every other landing gate passes and
before the branch lands, with ``--verification`` as the reason. Reaching the
stage runs its own gates, so a gate refusal there stops the merge with the
gate's reason. An item further back is refused with the walk it still owes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from yoke_contracts.api.function_call import TargetRef
from yoke_core.api.service_client_structured_api_adapter import call_dispatcher
from yoke_core.domain import json_helper
from yoke_core.domain.public_item_target import public_item_target
from yoke_core.domain.workflow_declared_transitions import (
    declares_transition,
    unreached_review_stage,
)
from yoke_core.domain.workflow_registry import WorkflowRegistryError
from yoke_core.domain.workflow_runtime import (
    WorkflowRuntime,
    workflow_runtime_from_row,
)


def pinned_workflow_for_item(
    item: dict[str, Any],
) -> tuple[Optional[WorkflowRuntime], str]:
    """Load the definition the item pins. Returns ``(runtime, error)``.

    The pin is asked for exactly as the item names it, so a pin that names
    no workflow or no version fails as a read that could not be answered
    rather than as a second opinion about the payload's shape.
    """
    pin = item.get("workflow") or {}
    named = f"{pin.get('id') or '<unnamed>'}@{pin.get('version')}"
    response = call_dispatcher(
        function_id="workflows.version.get",
        target=TargetRef(kind="global"),
        payload={
            "workflow_id": pin.get("id") or "",
            "version": pin.get("version"),
        },
    )
    if not response.success:
        error = getattr(response, "error", None)
        detail = getattr(error, "message", None) or "workflow version read failed"
        return None, f"{named} could not be read: {detail}"
    result = response.result or {}
    try:
        runtime = workflow_runtime_from_row(
            {
                "workflow_version_id": result["version_id"],
                "workflow_id": result["workflow_id"],
                "version": result["version"],
                "definition_json": json_helper.dumps_compact(result["definition"]),
                "definition_digest": result["definition_digest"],
            }
        )
    except (KeyError, TypeError, ValueError, WorkflowRegistryError) as exc:
        return None, f"{named} could not be interpreted: {exc}"
    return runtime, ""


@dataclass(frozen=True)
class ReviewReadiness:
    """Whether the item may land, and the review entry the merge performs."""

    refusal: str = ""
    source_stage: str = ""
    review_stage: str = ""

    @property
    def enters_review(self) -> bool:
        return bool(self.review_stage)


def review_readiness(item: dict[str, Any], *, public_ref: str) -> ReviewReadiness:
    """Read the item's review position against its pinned workflow.

    Fails closed on a definition it cannot read: a merge boundary that
    cannot ask the question must not answer it with a landing.
    """
    status = str(item.get("status") or "")
    workflow, error = pinned_workflow_for_item(item)
    if workflow is None:
        return ReviewReadiness(
            refusal=(
                f"review readiness could not be checked because {error}. Merge "
                "admission reads the pinned workflow definition; resolve the "
                "control-plane read and re-run this merge."
            )
        )
    review_stage_id = unreached_review_stage(workflow, status)
    if not review_stage_id:
        return ReviewReadiness()
    if declares_transition(workflow, status, review_stage_id):
        return ReviewReadiness(source_stage=status, review_stage=review_stage_id)
    return ReviewReadiness(
        refusal=(
            f"{public_ref} is at {status!r} and "
            f"{workflow.workflow_id}@{workflow.version} declares review at "
            f"{review_stage_id!r}, more than one declared edge away. The merge "
            "enters review only from the stage directly before it, and "
            "--skip-status does not waive review. Walk the item's declared "
            f"edges with `yoke lifecycle transition {public_ref} --from "
            f'{status} --to <next stage> --reason "<why>"` until it is one '
            "edge before review, then re-run this merge."
        )
    )


def enter_review_stage(
    public_ref: str, readiness: ReviewReadiness, *, reason: str
) -> str:
    """Move the item into its review stage. Empty on success, else the refusal.

    The transition runs that stage's own gates on the control plane; their
    refusal is returned whole so the merge stops with the gate's reason.
    """
    from yoke_core.domain.workflow_level_handoff import record_level_handoff

    response = call_dispatcher(
        function_id="lifecycle.transition.execute",
        target=public_item_target(public_ref),
        payload={
            "source_status": readiness.source_stage,
            "target_status": readiness.review_stage,
            "reason": reason or "Verified; merge entered review",
        },
    )
    if response.success:
        record_level_handoff(dict(response.result or {}))
        return ""
    error = getattr(response, "error", None)
    detail = getattr(error, "message", None) or "transition refused"
    return (
        "the merge could not move the item from "
        f"{readiness.source_stage!r} to {readiness.review_stage!r}, so nothing "
        f"landed: {detail}\nResolve that stage gate, then re-run this merge."
    )


__all__ = [
    "ReviewReadiness",
    "enter_review_stage",
    "pinned_workflow_for_item",
    "review_readiness",
]
