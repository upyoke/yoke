"""Frontier-state assembly helper used by ``cmd_session_offer``.

Owns the CLI-side conversion from a ``SchedulerResult`` into a
``FrontierState``. Kept separate from ``service_client_sessions_offer`` so
each module stays well below the 350-line ceiling. Project scope is
resolved upstream by
``yoke_core.domain.session_project_scope.resolve_session_project_scope``.
"""

from __future__ import annotations

from yoke_core.domain.scheduler_types import is_assignable_claim_state
from yoke_core.domain.sessions_queries_base import normalize_claim_item_id
from yoke_core.api.service_client_shared import FrontierState


def build_frontier_state_from_schedule(
    schedule,
    drift_review_dict: dict | None = None,
    last_completed_step: dict | None = None,
    skip_memory_item_ids: set[str] | None = None,
) -> FrontierState:
    """Build a FrontierState from a SchedulerResult for the decision engine.

    ``runnable_items`` carries assignable work for the offering session only:
    ranked steps with ``claim_state='claimed_by_other_live'`` stay on the raw
    ranked frontier for diagnostics but are filtered out here so operator-facing
    output does not advertise live-claimed work as runnable. The shared
    assignability rule lives in ``yoke_core.domain.scheduler_types``.

    when ``skip_memory_item_ids`` is supplied, items the offer
    already skipped earlier in the same chain are filtered from
    ``runnable_items`` and from the ``selected_item`` / ``scheduler_context``
    dispatch fields. ``decide_next_action`` cannot pick an item the
    ownership block already gave up on, even if the offer command falls
    through to this branch with a stale schedule snapshot. The skip-memory
    filter sits on top of the ``is_assignable_claim_state`` filter
.
    """
    skip_ids = {normalize_claim_item_id(str(x)) for x in (skip_memory_item_ids or set())}

    selected_step = schedule.selected_step
    if selected_step is not None and normalize_claim_item_id(str(selected_step.item_id)) in skip_ids:
        # Scheduler's top pick is in skip-memory; promote the next surviving
        # ranked step so /yoke do charge dispatch still gets scheduler_context.
        # Same filter shape as the runnable_items projection below.
        selected_step = next(
            (
                s
                for s in schedule.ranked_steps
                if is_assignable_claim_state(s.claim_state)
                and normalize_claim_item_id(str(s.item_id)) not in skip_ids
            ),
            None,
        )
    selected_item = selected_step.item_id if selected_step else None
    scheduler_ctx: dict = {}
    if selected_step:
        ss = selected_step
        scheduler_ctx = {
            "next_step": ss.next_step.value if hasattr(ss.next_step, "value") else str(ss.next_step),
            "item_type": ss.item_type,
            "status": ss.status,
            "title": ss.title,
            "rank": ss.rank,
            "explanation": ss.explanation,
            "adapter": ss.adapter,
            # Carries the schedule's authoritative selected item id so
            # the decide_charge_action mismatch guard at
            # session_decision_charge.py (which reads
            # scheduler_context["selected_item"]) can fire reliably,
            # and so SessionOfferInvariantFailed carries a non-null
            # schedule_selected_item when the action context has a
            # scheduler block.
            "selected_item": ss.item_id,
        }
        ro = getattr(ss, "routing_override", None)
        if ro is not None:
            scheduler_ctx.update(ro.to_context_dict())
    blocked_details_list = []
    intrinsic_reasons_list = []
    for bs in schedule.blocked_steps:
        for ge in bs.gate_evaluations:
            if not ge.satisfied:
                blocked_details_list.append({
                    "item_id": bs.item_id,
                    "blocking_item": ge.blocking_item,
                    "gate_point": ge.gate_point,
                    "satisfaction": ge.satisfaction,
                    "rationale": getattr(ge, "rationale", ""),
                    "reason": ge.reason,
                })
        intrinsic_reasons = getattr(bs, "blocked_reasons", None) or []
        if intrinsic_reasons:
            intrinsic_reasons_list.append({
                "item_id": bs.item_id,
                "status": getattr(bs, "status", ""),
                "reasons": list(intrinsic_reasons),
            })
    lane_filtered_items = getattr(schedule, "lane_filtered_items", None)
    runnable = [
        s.item_id
        for s in schedule.ranked_steps
        if is_assignable_claim_state(s.claim_state)
        and normalize_claim_item_id(str(s.item_id)) not in skip_ids
    ]
    return FrontierState(
        runnable_items=runnable,
        blocked_items=[s.item_id for s in schedule.blocked_steps],
        exceptional_items=[s.item_id for s in schedule.exceptional_steps],
        blocked_details=blocked_details_list if blocked_details_list else None,
        intrinsic_blocked_reasons=intrinsic_reasons_list if intrinsic_reasons_list else None,
        sml_coherent=schedule.sml_state.coherent,
        drift_review=drift_review_dict,
        selected_item=selected_item,
        scheduler_context=scheduler_ctx,
        lane_filtered_count=getattr(schedule, "lane_filtered_count", 0),
        lane_filtered_items=list(lane_filtered_items) if lane_filtered_items else None,
        last_completed_step=last_completed_step,
    )


__all__ = [
    "build_frontier_state_from_schedule",
]
