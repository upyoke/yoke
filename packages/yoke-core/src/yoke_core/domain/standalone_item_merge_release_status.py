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
from yoke_core.domain.delivery_discharge_read import delivery_discharge
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

    ``delivery_discharged`` is true when this close-out has performed the
    whole of the item's delivery ceremony rather than owing one to a later
    deploy. Two ways reach that. The item's registered deployment flow
    resolved merge-only, so the merge that just landed IS its delivery. Or
    the item is re-entering at its release wait and the delivery it was
    waiting for has since succeeded — the deploy happened, so the ceremony
    it owed is performed, and there is nothing left for a later run to do.
    An item still waiting on a delivery that has not run is never marked
    discharged, and stops at its pinned release wait instead.

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


def close_out_route(
    item: dict[str, Any],
    status: str,
    *,
    postpone_terminal: bool = False,
) -> CloseOutRoute:
    """Resolve where this merge's terminal transition should land.

    ``postpone_terminal`` is ``--skip-status``: still enter the pinned
    release wait so a completed merge is not stranded in review, but do
    not walk to ``done``. Workflows with no release wait keep the historical
    no-op. Mid-progress slices that cannot legally reach the wait stay put.
    """
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
    if postpone_terminal:
        if release_stage_id is None:
            return CloseOutRoute()
        if workflow.has_reached_stage(status, release_stage_id):
            return CloseOutRoute()
        if not declares_transition(workflow, status, release_stage_id):
            return CloseOutRoute()
        return CloseOutRoute(stages=(release_stage_id,))
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
        # Re-entry at the release wait: the delivery this item waited for may
        # have happened since. Keying the ceremony on ``merge_only`` alone
        # asserted it for exactly the items that never owed a deploy, and
        # withheld it from every item whose deploy had just succeeded — so a
        # delivered member's close-out recorded its evidence and was then
        # refused done for a ceremony nobody could perform.
        if clearance.merge_only:
            return CloseOutRoute(
                stages=(CLOSED_OUT_STATUS,), delivery_discharged=True
            )
        discharge = delivery_discharge(item)
        if discharge.unread:
            # Never assert a ceremony on an unread delivery — but never hide
            # the unread state either. Refusing here names the provider's own
            # reason, where letting it read as "not delivered" would hand the
            # owner the undiagnosable nonce refusal instead.
            return CloseOutRoute(
                error=(
                    "whether this item's delivery has happened could not be "
                    f"read: {discharge.detail}. {discharge.recovery}"
                )
            )
        return CloseOutRoute(
            stages=(CLOSED_OUT_STATUS,),
            delivery_discharged=discharge.discharged,
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


def stale_mismatch_is_foreign(item: dict[str, Any], status: str) -> bool:
    """Whether a mismatched lane head is foreign/stale work at close-out.

    A workflow that owns a release wait treats this item's own new
    commits as the next governed merge until ``done``, including while
    the item waits at that release stage. Workflows with no release wait,
    and unreadable definitions, keep the existing refusal.
    """
    if status == CLOSED_OUT_STATUS:
        return True
    workflow, error = pinned_workflow_for_item(item)
    if workflow is None or error:
        return True
    if delivery_redirect_stage(workflow) is None:
        return True
    return False


__all__ = [
    "CloseOutRoute",
    "close_out_route",
    "reached_release",
    "stale_mismatch_is_foreign",
]
