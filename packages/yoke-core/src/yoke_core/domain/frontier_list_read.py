"""Read-only frontier projection from one scheduler pass.

Ready rows carry ranks, routed steps, and readiness reasons. Blocked rows
cover unsatisfied activation, integration, and closure dependencies, plus
operator blocks and incomplete bodies. Dependency edges and deadlocks serve
the Waiting graph (:mod:`frontier_dependency_edges`). Polling emits no events.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from yoke_contracts.public_ref import format_item_ref
from yoke_core.domain import db_helpers
from yoke_core.domain.dependency_planning import (
    BlockerDetail,
    evaluate_batch_gates,
)
from yoke_core.domain.dependency_cycles_read import BLOCKING_GATE_POINTS
from yoke_core.domain.frontier_blocked_rows import (
    FRONTIER_BLOCKED_FIELDS,
    blocked_row,
)
from yoke_core.domain.frontier_dependency_edges import (
    FRONTIER_CYCLE_FIELDS,
    FRONTIER_EDGE_FIELDS,
    frontier_dependency_graph,
)
from yoke_core.domain.item_ref_resolution import internal_ids_for_refs
from yoke_core.domain.project_identity import placeholder
from yoke_core.domain.scheduler import compute_schedule
from yoke_core.domain.scheduler_types import (
    ClaimState,
    GateEvaluation,
    NextStep,
    ScheduledStep,
)
from yoke_core.domain.session_project_scope import resolve_session_project_scope


#: Ready-row keys, in presentation order.
FRONTIER_READY_FIELDS = (
    "rank",
    "item_id",
    "title",
    "workflow_id",
    "workflow_version",
    "project",
    "project_id",
    "project_sequence",
    "status",
    "stage_index",
    "stage_count",
    "stage_label",
    "priority",
    "next_step",
    "why_ready",
    "unblocks_count",
    "downstream_depth",
    "created_at",
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


def _item_route_facts(
    conn: Any,
    item_ids: set[int],
) -> Dict[int, Dict[str, Any]]:
    ids = sorted({int(item_id) for item_id in item_ids})
    if not ids:
        return {}
    marker = placeholder(conn)
    rows = conn.execute(
        "SELECT i.id, i.project_id, i.project_sequence, p.slug, "
        "p.public_item_prefix FROM items i "
        "JOIN projects p ON p.id = i.project_id "
        f"WHERE i.id IN ({', '.join(marker for _ in ids)})",
        tuple(ids),
    ).fetchall()
    facts: Dict[int, Dict[str, Any]] = {}
    for row in rows:
        sequence = int(row["project_sequence"])
        facts[int(row["id"])] = {
            "project_id": int(row["project_id"]),
            "project_sequence": sequence,
            "public_ref": format_item_ref(
                row["slug"],
                row["public_item_prefix"],
                sequence,
            ),
        }
    return facts


def list_frontier(
    *,
    project: Optional[str] = None,
    wip_cap: Optional[int] = None,
) -> Dict[str, Any]:
    """Project the frontier for one project or every registered project.

    ``project`` omitted resolves to the all-projects default (the same
    scope rule charge uses). Unknown projects raise ``ValueError``
    naming the registered set.
    """
    conn = db_helpers.connect()
    try:
        scope = resolve_session_project_scope(
            conn,
            override=[project] if project else None,
        )
        schedule_kwargs: Dict[str, Any] = {"emit_events": False}
        if wip_cap is not None:
            schedule_kwargs["wip_cap"] = int(wip_cap)
        schedule = compute_schedule(conn, scope, **schedule_kwargs)

        # Later-landing edges attach to whichever non-terminal step the
        # schedule already tracks for the dependent item — an edge whose
        # dependent is terminal (or out of scope) has nothing left to gate.
        # Edge rows carry public text refs; resolve them to internal ids
        # before matching against tracked steps.
        tracked_steps: Dict[int, ScheduledStep] = {}
        for step_list in (
            schedule.ranked_steps,
            schedule.blocked_steps,
            schedule.frozen_steps,
            schedule.exceptional_steps,
        ):
            for step in step_list:
                tracked_steps.setdefault(step.item_id, step)
        # Each spec: the step, one holding edge (or None), and whether that
        # edge is why the scheduler is not offering the item.
        blocked_specs: List[
            tuple[ScheduledStep, Optional[BlockerDetail | GateEvaluation], bool]
        ] = []
        for step in schedule.blocked_steps:
            blocked_specs.extend(
                (step, gate, True) for gate in (step.gate_evaluations or [None])
            )
        own = {
            (step.item_id, gate.gate_point, gate.blocking_item)
            for step, gate, _holds in blocked_specs
            if gate is not None
        }
        # Each gate is evaluated once per read; the dependency edges reuse it.
        gate_blocks = {
            gate: evaluate_batch_gates(conn, gate_point=gate, emit_events=False)
            for gate in BLOCKING_GATE_POINTS
        }
        for gate_point in _LATER_GATE_POINTS:
            blocks = gate_blocks[gate_point]
            dependent_ids = internal_ids_for_refs(conn, blocks.keys())
            for dependent_item in sorted(blocks):
                step = tracked_steps.get(dependent_ids.get(dependent_item, -1))
                if step is None:
                    continue
                for detail in blocks[dependent_item]:
                    key = (step.item_id, detail.gate_point, detail.blocking_item)
                    if key not in own:
                        blocked_specs.append((step, detail, False))

        blocking_ids = internal_ids_for_refs(
            conn,
            (
                detail.blocking_item
                for _step, detail, _holds in blocked_specs
                if detail is not None and detail.blocking_item
            ),
        )
        route_facts = _item_route_facts(
            conn,
            set(tracked_steps) | set(blocking_ids.values()),
        )
        public_refs = {
            item_id: str(route_facts[item_id]["public_ref"])
            for item_id in tracked_steps
        }
        conduct_eligible_ids = {step.item_id for step in schedule.conduct_eligible}
        ready_rows: List[Dict[str, Any]] = []
        for step in schedule.ranked_steps:
            public_ref = public_refs[step.item_id]
            ready_rows.append(
                {
                    "rank": step.rank,
                    "item_id": public_ref,
                    "title": step.title,
                    "workflow_id": step.workflow_id,
                    "workflow_version": step.workflow_version,
                    "project": step.project,
                    "project_id": route_facts[step.item_id]["project_id"],
                    "project_sequence": route_facts[step.item_id]["project_sequence"],
                    "status": step.status,
                    "stage_index": step.stage_index,
                    "stage_count": step.stage_count,
                    "stage_label": step.stage_label,
                    "priority": step.priority,
                    "next_step": step.next_step.value,
                    "why_ready": _compose_why_ready(
                        step,
                        conduct_eligible_ids=conduct_eligible_ids,
                        wip_cap=schedule.wip_cap,
                        wip_active=schedule.wip_active,
                    ),
                    "unblocks_count": step.unblocks_count,
                    "downstream_depth": step.downstream_depth,
                    "created_at": step.created_at,
                }
            )

        blocked_rows: List[Dict[str, Any]] = []
        for step, detail, holds_pickup in blocked_specs:
            blocking_route = (
                None
                if detail is None
                else route_facts.get(
                    blocking_ids.get(detail.blocking_item, -1),
                )
            )
            blocked_rows.append(
                blocked_row(
                    step,
                    detail,
                    public_refs[step.item_id],
                    route_facts[step.item_id],
                    blocking_route,
                    holds_pickup=holds_pickup,
                )
            )

        return {
            "fields": {
                "ready": list(FRONTIER_READY_FIELDS),
                "blocked": list(FRONTIER_BLOCKED_FIELDS),
                "dependency_edges": list(FRONTIER_EDGE_FIELDS),
                "dependency_cycles": list(FRONTIER_CYCLE_FIELDS),
            },
            "ready_rows": ready_rows,
            "blocked_rows": blocked_rows,
            **frontier_dependency_graph(conn, scope, gate_blocks=gate_blocks),
            "frozen_count": len(schedule.frozen_steps),
            "wip_cap": schedule.wip_cap,
            "wip_active": schedule.wip_active,
            "waiting_on_you_count": len(
                {
                    step.item_id
                    for step in schedule.blocked_steps
                    if any(
                        str(reason).startswith("Blocked by operator")
                        for reason in step.blocked_reasons
                    )
                }
            ),
        }
    finally:
        conn.close()


__all__ = [
    "FRONTIER_BLOCKED_FIELDS",
    "FRONTIER_READY_FIELDS",
    "list_frontier",
]
