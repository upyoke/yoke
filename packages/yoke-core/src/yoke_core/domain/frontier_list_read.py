"""Read-only frontier projection: what runs next and what waits on what.

The read behind ``frontier.list``: two row families rendered from one
:func:`yoke_core.domain.scheduler.compute_schedule` pass with
``emit_events=False`` (a poll must not write an event row per refresh).

* ``ready_rows`` — the ranked runnable steps, each carrying the engine's
  own rank (never a display index), the routed next-step verb, a
  copyable ``run_command``, and a ``why_ready`` sentence composed here
  from the computed facts (activation gates clear, claim state, WIP
  headroom for conduct steps, downstream leverage).
* ``blocked_rows`` — one row per unsatisfied dependency edge, across all
  three gate points. Activation edges come from the schedule's blocked
  steps; integration and closure edges are evaluated separately because
  the frontier computation only enforces activation, so an item gated
  solely by a later-landing edge is runnable *and* still owes that edge
  a visible row. Non-edge waits (operator blocks, incomplete idea
  bodies) render with an empty ``blocking_item``/``gate_point`` so the
  waiting item is never silently absent.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from yoke_core.domain import db_helpers
from yoke_core.domain.dependency_planning import BlockerDetail, evaluate_batch_gates
from yoke_core.domain.scheduler import compute_schedule
from yoke_core.domain.scheduler_types import ClaimState, NextStep, ScheduledStep
from yoke_core.domain.session_project_scope import resolve_session_project_scope


#: Ready-row keys, in presentation order.
FRONTIER_READY_FIELDS = (
    "rank",
    "item_id",
    "title",
    "item_type",
    "project",
    "status",
    "priority",
    "next_step",
    "run_command",
    "why_ready",
    "unblocks_count",
    "downstream_depth",
)

#: Blocked-row keys, in presentation order.
FRONTIER_BLOCKED_FIELDS = (
    "item_id",
    "title",
    "project",
    "blocking_item",
    "gate_point",
    "why",
    "satisfaction",
)

#: Gate points the frontier computation does not enforce but whose
#: unsatisfied edges the blocked view still owes a row for.
_LATER_GATE_POINTS = ("integration", "closure")

_CLAIM_STATE_PROSE = {
    ClaimState.UNCLAIMED: "unclaimed",
    ClaimState.CLAIMED_BY_SELF: "claimed by this session",
    ClaimState.CLAIMED_BY_STALE: "prior claim is stale and reclaimable",
    ClaimState.CLAIMED_BY_OTHER_LIVE: "claimed by another live session",
}


def _compose_why_ready(
    step: ScheduledStep,
    *,
    conduct_eligible_ids: set,
    wip_cap: int,
    wip_active: int,
) -> str:
    """Render the engine's readiness facts as one short sentence."""
    parts = ["no unsatisfied activation gates"]
    parts.append(_CLAIM_STATE_PROSE.get(step.claim_state, str(step.claim_state)))
    if step.next_step is NextStep.CONDUCT:
        headroom = "within" if step.item_id in conduct_eligible_ids else "beyond"
        parts.append(f"{headroom} WIP headroom ({wip_active} of {wip_cap} active)")
    if step.unblocks_count:
        plural = "s" if step.unblocks_count != 1 else ""
        parts.append(f"unblocks {step.unblocks_count} item{plural}")
    if step.downstream_depth:
        parts.append(f"downstream depth {step.downstream_depth}")
    sentence = "; ".join(parts)
    return sentence[0].upper() + sentence[1:] + "."


def _compose_edge_why(reason: str, rationale: str) -> str:
    """Join the evaluation reason with the persisted edge rationale."""
    if rationale:
        return f"{reason} — {rationale}" if reason else rationale
    return reason


def _blocked_row(step: ScheduledStep, detail: Optional[BlockerDetail]) -> Dict[str, Any]:
    if detail is None:
        # Non-edge wait: operator block, legacy blocked status, or an
        # incomplete idea body. There is no blocking item or gate point;
        # the reasons channel carries the whole story.
        return {
            "item_id": step.item_id,
            "title": step.title,
            "project": step.project,
            "blocking_item": "",
            "gate_point": "",
            "why": "; ".join(step.blocked_reasons) or step.explanation,
            "satisfaction": "",
        }
    return {
        "item_id": step.item_id,
        "title": step.title,
        "project": step.project,
        "blocking_item": detail.blocking_item,
        "gate_point": detail.gate_point,
        "why": _compose_edge_why(detail.reason, detail.rationale),
        "satisfaction": detail.satisfaction,
    }


def list_frontier(
    *,
    project: Optional[str] = None,
    wip_cap: Optional[int] = None,
) -> Dict[str, Any]:
    """Project the frontier for one project or every registered project.

    ``project`` omitted resolves to the all-projects default (the same
    scope rule ``/yoke do`` uses). Unknown projects raise ``ValueError``
    naming the registered set.
    """
    conn = db_helpers.connect()
    try:
        scope = resolve_session_project_scope(
            conn, override=[project] if project else None,
        )
        schedule_kwargs: Dict[str, Any] = {"emit_events": False}
        if wip_cap is not None:
            schedule_kwargs["wip_cap"] = int(wip_cap)
        schedule = compute_schedule(conn, scope, **schedule_kwargs)

        conduct_eligible_ids = {
            step.item_id for step in schedule.conduct_eligible
        }
        ready_rows: List[Dict[str, Any]] = []
        for step in schedule.ranked_steps:
            ready_rows.append({
                "rank": step.rank,
                "item_id": step.item_id,
                "title": step.title,
                "item_type": step.item_type,
                "project": step.project,
                "status": step.status,
                "priority": step.priority,
                "next_step": step.next_step.value,
                "run_command": f"yoke {step.next_step.value} {step.item_id}",
                "why_ready": _compose_why_ready(
                    step,
                    conduct_eligible_ids=conduct_eligible_ids,
                    wip_cap=schedule.wip_cap,
                    wip_active=schedule.wip_active,
                ),
                "unblocks_count": step.unblocks_count,
                "downstream_depth": step.downstream_depth,
            })

        blocked_rows: List[Dict[str, Any]] = []
        for step in schedule.blocked_steps:
            if not step.gate_evaluations:
                blocked_rows.append(_blocked_row(step, None))
                continue
            for gate in step.gate_evaluations:
                blocked_rows.append({
                    "item_id": step.item_id,
                    "title": step.title,
                    "project": step.project,
                    "blocking_item": gate.blocking_item,
                    "gate_point": gate.gate_point,
                    "why": _compose_edge_why(gate.reason, gate.rationale),
                    "satisfaction": gate.satisfaction,
                })

        # Later-landing edges attach to whichever non-terminal step the
        # schedule already tracks for the dependent item — an edge whose
        # dependent is terminal (or out of scope) has nothing left to gate.
        tracked_steps: Dict[str, ScheduledStep] = {}
        for step_list in (
            schedule.ranked_steps,
            schedule.blocked_steps,
            schedule.frozen_steps,
            schedule.exceptional_steps,
        ):
            for step in step_list:
                tracked_steps.setdefault(step.item_id, step)
        for gate_point in _LATER_GATE_POINTS:
            gate_blocks = evaluate_batch_gates(
                conn, gate_point=gate_point, emit_events=False,
            )
            for dependent_item in sorted(gate_blocks):
                step = tracked_steps.get(dependent_item)
                if step is None:
                    continue
                for detail in gate_blocks[dependent_item]:
                    blocked_rows.append(_blocked_row(step, detail))

        return {
            "fields": {
                "ready": list(FRONTIER_READY_FIELDS),
                "blocked": list(FRONTIER_BLOCKED_FIELDS),
            },
            "ready_rows": ready_rows,
            "blocked_rows": blocked_rows,
            "frozen_count": len(schedule.frozen_steps),
            "wip_cap": schedule.wip_cap,
            "wip_active": schedule.wip_active,
        }
    finally:
        conn.close()


__all__ = [
    "FRONTIER_BLOCKED_FIELDS",
    "FRONTIER_READY_FIELDS",
    "list_frontier",
]
