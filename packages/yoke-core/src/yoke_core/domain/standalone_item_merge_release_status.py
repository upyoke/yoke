"""Has an item's live status reached its pinned release wait.

Split out of :mod:`standalone_item_merge_cli` to stay under the authored
file line budget; used only there, to decide whether a mismatched branch
head at the merge boundary is foreign/stale work or this same item's own
next legitimate merge attempt after genuinely returning short of release.
"""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain.deployment_flow_clearance import resolve_delivery_clearance
from yoke_core.domain.merge_review_readiness import pinned_workflow_for_item
from yoke_core.domain.workflow_behavior import delivery_redirect_stage
from yoke_core.domain.workflow_declared_transitions import declares_transition


def release_redirect_stage(item: dict[str, Any], status: str) -> tuple[Optional[str], str]:
    """Resolve where this merge's terminal transition should land.

    Returns ``(target, error)``.

    ``error`` is non-empty when the decision itself could not be made -- an
    unreadable pinned definition, or an unread deployment-flow authority --
    and the terminal transition must be refused rather than guessed as
    either clear or pending, matching every other fail-closed read at this
    boundary (a definition or a flow this call could not read is not the
    same fact as "clear for done").

    On no error, ``target``:
    - is ``None``: proceed straight to ``done`` -- no release-stage
      concept, the status already reached the release stage, or delivery
      is discharged (the shared :mod:`deployment_flow_clearance` verdict).
    - equals ``status``: nothing to do yet. The pinned delivery will
      require a release wait eventually, but ``status`` cannot legally
      reach that stage in one declared step from here -- mid-progress work
      such as a still-implementing Blitz slice, whose continuous-per-slice
      delivery is not forced into an early release by stage order alone.
    - is a different stage id: land there instead of ``done``.
    """
    workflow, wf_error = pinned_workflow_for_item(item)
    if workflow is None or wf_error:
        return None, wf_error or "the pinned workflow definition could not be read"
    stage_id = delivery_redirect_stage(workflow)
    if stage_id is None or workflow.has_reached_stage(status, stage_id):
        return None, ""
    if not declares_transition(workflow, status, stage_id):
        return status, ""
    try:
        clearance = resolve_delivery_clearance(
            deploy_flow=str(item.get("deployment_flow") or ""),
            item_project=str((item.get("project") or {}).get("slug") or ""),
            workflow_id=workflow.workflow_id,
        )
    except RuntimeError as exc:
        return None, str(exc)
    if clearance.blocked_reason:
        return None, clearance.blocked_reason
    return (None if clearance.merge_only else stage_id), ""


def reached_release(item: dict[str, Any], status: str) -> bool:
    """``True`` (the safe default) on a workflow with no release-stage
    concept, or on a definition read that fails -- both keep
    ``stale_unlanded_work``'s existing foreign/stale-work refusal exactly
    as it already behaves. Only a workflow that both owns a release wait
    AND whose item has genuinely returned short of it (a fix in progress
    after a failed release-stage verdict) answers ``False``.
    """
    workflow, error = pinned_workflow_for_item(item)
    if workflow is None or error:
        return True
    release_stage_id = delivery_redirect_stage(workflow)
    if release_stage_id is None:
        return True
    return workflow.has_reached_stage(status, release_stage_id)


__all__ = ["reached_release", "release_redirect_stage"]
