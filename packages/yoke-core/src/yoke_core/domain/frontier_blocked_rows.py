"""One ``frontier.list`` blocked row: an item, and one thing holding it.

A waiting item gets one row per unsatisfied edge, or one row naming a
non-edge wait (an operator block, an incomplete body, a defended prior
owner). ``holds_pickup`` says whether the row is why the scheduler is not
offering the item. A merge or close edge on an item still free to start is
reported for the Waiting graph but holds nothing back; committed work waiting
only for its blockers to land
(:mod:`yoke_core.domain.frontier_landing_wait`) is held by exactly those
edges, so its rows hold pickup and carry the shared waiting sentence.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from yoke_core.domain.dependency_planning import BlockerDetail
from yoke_core.domain.frontier_landing_wait import landing_wait_reason
from yoke_core.domain.scheduler_types import GateEvaluation, ScheduledStep

#: Blocked-row keys, in presentation order.
FRONTIER_BLOCKED_FIELDS = (
    "item_id",
    "title",
    "workflow_id",
    "project",
    "project_id",
    "project_sequence",
    "blocking_item",
    "blocking_project_id",
    "blocking_project_sequence",
    "gate_point",
    "why",
    "satisfaction",
    "needs_spec",
    "holds_pickup",
    "created_at",
)


def compose_edge_why(reason: str, rationale: str) -> str:
    """Join the evaluation reason with the persisted edge rationale."""
    if rationale:
        return f"{reason} — {rationale}" if reason else rationale
    return reason


def _edge_why(step: ScheduledStep, detail: BlockerDetail | GateEvaluation) -> str:
    """The shared waiting sentence for a landing wait; the edge's own otherwise."""
    if detail.gate_point != "activation":
        landing = [
            (gate.blocking_item, gate.satisfaction)
            for gate in step.gate_evaluations
            if gate.gate_point == detail.gate_point
        ]
        if landing:
            return landing_wait_reason(landing)
    return compose_edge_why(detail.reason, detail.rationale)


def blocked_row(
    step: ScheduledStep,
    detail: Optional[BlockerDetail | GateEvaluation],
    public_ref: str,
    item_route: Dict[str, Any],
    blocking_route: Optional[Dict[str, Any]],
    *,
    holds_pickup: bool,
) -> Dict[str, Any]:
    """One row; ``holds_pickup`` is true for the step's own wait reasons."""
    row: Dict[str, Any] = {
        "item_id": public_ref,
        "title": step.title,
        "workflow_id": step.workflow_id,
        "project": step.project,
        "project_id": item_route["project_id"],
        "project_sequence": item_route["project_sequence"],
        "needs_spec": step.needs_spec,
        "holds_pickup": holds_pickup,
        "created_at": step.created_at,
    }
    if detail is None:
        # Non-edge wait: no blocking item or gate point; reasons say why.
        row.update(
            blocking_item="",
            blocking_project_id=None,
            blocking_project_sequence=None,
            gate_point="",
            why="; ".join(step.blocked_reasons) or step.explanation,
            satisfaction="",
        )
    else:
        row.update(
            blocking_item=detail.blocking_item,
            blocking_project_id=(blocking_route or {}).get("project_id"),
            blocking_project_sequence=(blocking_route or {}).get("project_sequence"),
            gate_point=detail.gate_point,
            why=_edge_why(step, detail)
            if holds_pickup
            else compose_edge_why(detail.reason, detail.rationale),
            satisfaction=detail.satisfaction,
        )
    return {field: row[field] for field in FRONTIER_BLOCKED_FIELDS}


__all__ = ["FRONTIER_BLOCKED_FIELDS", "blocked_row", "compose_edge_why"]
