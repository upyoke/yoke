"""Where a landed standalone merge's close-out takes the item.

Split out of :mod:`standalone_item_merge_cli` to stay under the authored
file line budget; used there to decide whether a mismatched branch head at
the merge boundary is foreign/stale work or this same item's own next
legitimate merge while still short of a declared release wait, and to
resolve the declared route the terminal transition walks.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from yoke_core.domain.deployment_flow_clearance import resolve_delivery_clearance
from yoke_core.domain.merge_review_readiness import pinned_workflow_for_item
from yoke_core.domain.standalone_item_merge_evidence import CLOSED_OUT_STATUS
from yoke_core.domain.workflow_behavior import delivery_redirect_stage
from yoke_core.domain.workflow_declared_transitions import declares_transition


@dataclass(frozen=True)
class CloseOutRoute:
    """The declared stages this close-out walks, and by whose authority.

    ``stages`` is empty when nothing applies here yet -- mid-progress work
    such as a still-implementing Blitz slice, whose continuous-per-slice
    delivery is not forced into an early release by stage order alone.
    Otherwise it is the ordered stage ids to transition through, each one a
    declared edge so every stage in between runs its own gates.

    ``delivery_discharged`` is true only when the item's own registered
    deployment flow resolved merge-only: the merge that just landed is the
    whole of its delivery, so this close-out has performed the
    done-transition ceremony rather than owing one to a later deploy. A
    delivery-required item is never marked discharged, and stops at its
    pinned release wait instead.

    ``error`` is non-empty when the decision itself could not be made -- an
    unreadable pinned definition, an unread deployment-flow authority, or a
    definition that declares no route from the release wait to the terminal
    stage -- and the terminal transition must be refused rather than guessed
    as either clear or pending, matching every other fail-closed read at
    this boundary (a definition or a flow this call could not read is not
    the same fact as "clear for done").
    """

    stages: tuple[str, ...] = ()
    delivery_discharged: bool = False
    error: str = ""


def close_out_route(item: dict[str, Any], status: str) -> CloseOutRoute:
    """Resolve where this merge's terminal transition should land."""
    if status == CLOSED_OUT_STATUS:
        # Already closed out. A re-entry here owes the lane its retirement,
        # not a route, and asking the delivery authority about an item that
        # has nowhere left to go turns an unconfigured flow into a refusal
        # on work that is finished.
        return CloseOutRoute(stages=(CLOSED_OUT_STATUS,))
    workflow, wf_error = pinned_workflow_for_item(item)
    if workflow is None or wf_error:
        return CloseOutRoute(
            error=wf_error or "the pinned workflow definition could not be read"
        )
    release_stage_id = delivery_redirect_stage(workflow)
    if release_stage_id is None:
        return CloseOutRoute(stages=(CLOSED_OUT_STATUS,))
    try:
        clearance = resolve_delivery_clearance(
            deploy_flow=str(item.get("deployment_flow") or ""),
            item_project=str((item.get("project") or {}).get("slug") or ""),
            workflow_id=workflow.workflow_id,
        )
    except RuntimeError as exc:
        return CloseOutRoute(error=str(exc))
    if clearance.blocked_reason:
        return CloseOutRoute(error=clearance.blocked_reason)
    if workflow.has_reached_stage(status, release_stage_id):
        return CloseOutRoute(
            stages=(CLOSED_OUT_STATUS,),
            delivery_discharged=clearance.merge_only,
        )
    if not declares_transition(workflow, status, release_stage_id):
        return CloseOutRoute()
    if not clearance.merge_only:
        return CloseOutRoute(stages=(release_stage_id,))
    if declares_transition(workflow, status, CLOSED_OUT_STATUS):
        return CloseOutRoute(stages=(CLOSED_OUT_STATUS,), delivery_discharged=True)
    if not declares_transition(workflow, release_stage_id, CLOSED_OUT_STATUS):
        return CloseOutRoute(
            error=(
                f"{workflow.workflow_id}@{workflow.version} declares no "
                f"transition {release_stage_id!r} -> {CLOSED_OUT_STATUS!r}, so a "
                f"merge-only item cannot finish through its release wait. "
                f"Declare that edge in the workflow definition, or select a "
                f"deployment flow whose delivery this release wait can hold."
            )
        )
    return CloseOutRoute(
        stages=(release_stage_id, CLOSED_OUT_STATUS), delivery_discharged=True,
    )


def reached_release(item: dict[str, Any], status: str) -> bool:
    """``True`` (the safe default) on a workflow with no release-stage
    concept, or on a definition read that fails -- both keep
    ``stale_unlanded_work``'s existing foreign/stale-work refusal exactly
    as it already behaves. Only a workflow that both owns a release wait
    AND whose item is still short of it (a fix in progress after a failed
    release-stage verdict) answers ``False``.
    """
    workflow, error = pinned_workflow_for_item(item)
    if workflow is None or error:
        return True
    release_stage_id = delivery_redirect_stage(workflow)
    if release_stage_id is None:
        return True
    return workflow.has_reached_stage(status, release_stage_id)


__all__ = ["CloseOutRoute", "close_out_route", "reached_release"]
