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

import re
from typing import AbstractSet, Any, Dict, List, Optional

from yoke_core.domain.dependency_planning import BlockerDetail
from yoke_core.domain.frontier_dependency_edges import HIDDEN_BLOCKER_TITLE
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

#: Why a row waits on an item the reader cannot see; it names nothing of it.
HIDDEN_BLOCKER_WHY = HIDDEN_BLOCKER_TITLE


def _names_any(text: str, refs: AbstractSet[str]) -> bool:
    return any(
        re.search(rf"(?<![\w-]){re.escape(ref)}(?!\d)", text) for ref in refs
    )


def _step_why(step: ScheduledStep, hidden_refs: AbstractSet[str]) -> str:
    """The step's own wait reasons, with any naming hidden work replaced."""
    reasons = [
        reason
        for reason in step.blocked_reasons
        if not _names_any(str(reason), hidden_refs)
    ]
    if len(reasons) < len(step.blocked_reasons):
        reasons.append(HIDDEN_BLOCKER_WHY)
    if reasons:
        return "; ".join(reasons)
    explanation = str(step.explanation or "")
    return HIDDEN_BLOCKER_WHY if _names_any(explanation, hidden_refs) else explanation


def compose_edge_why(reason: str, rationale: str) -> str:
    """Join the evaluation reason with the persisted edge rationale."""
    if rationale:
        return f"{reason} — {rationale}" if reason else rationale
    return reason


def _edge_why(
    step: ScheduledStep,
    detail: BlockerDetail | GateEvaluation,
    hidden_refs: AbstractSet[str],
) -> str:
    """The shared waiting sentence for a landing wait; the edge's own otherwise.

    A landing sentence leaves out blockers the reader cannot see.
    """
    if detail.gate_point != "activation":
        landing = [
            (gate.blocking_item, gate.satisfaction)
            for gate in step.gate_evaluations
            if gate.gate_point == detail.gate_point
            and gate.blocking_item not in hidden_refs
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
    hidden_refs: AbstractSet[str] = frozenset(),
) -> Dict[str, Any]:
    """One row; ``holds_pickup`` is true for the step's own wait reasons.

    A blocker in ``hidden_refs`` sits in a project the reader cannot see:
    the row still waits, but names no ref, project or rationale of it.
    """
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
            why=_step_why(step, hidden_refs),
            satisfaction="",
        )
    elif detail.blocking_item in hidden_refs:
        row.update(
            blocking_item="",
            blocking_project_id=None,
            blocking_project_sequence=None,
            gate_point=detail.gate_point,
            why=HIDDEN_BLOCKER_WHY,
            satisfaction=detail.satisfaction,
        )
    else:
        row.update(
            blocking_item=detail.blocking_item,
            blocking_project_id=(blocking_route or {}).get("project_id"),
            blocking_project_sequence=(blocking_route or {}).get("project_sequence"),
            gate_point=detail.gate_point,
            why=_edge_why(step, detail, hidden_refs)
            if holds_pickup
            else compose_edge_why(detail.reason, detail.rationale),
            satisfaction=detail.satisfaction,
        )
    return {field: row[field] for field in FRONTIER_BLOCKED_FIELDS}


def redact_next_actors(
    conn: Any, rows: List[Dict[str, Any]], visible: Optional[AbstractSet[int]]
) -> None:
    """Blank a ``next_actor`` blocker that sits in a project outside ``visible``.

    The shared item projection names the item a row waits on; a reader who
    cannot see that item learns only that another item holds the row.
    """
    if visible is None:
        return
    actors = [
        row["next_actor"]
        for row in rows
        if isinstance(row.get("next_actor"), dict)
        and row["next_actor"].get("blocking_item")
    ]
    if not actors:
        return
    from yoke_core.domain.item_ref_resolution import internal_ids_for_refs
    from yoke_core.domain.project_identity import placeholder

    ids = internal_ids_for_refs(conn, {str(a["blocking_item"]) for a in actors})
    projects: Dict[int, int] = {}
    if ids:
        marker = placeholder(conn)
        projects = {
            int(row["id"]): int(row["project_id"])
            for row in conn.execute(
                "SELECT id, project_id FROM items WHERE id IN "
                f"({', '.join(marker for _ in ids)})",
                tuple(ids.values()),
            ).fetchall()
        }
    for actor in actors:
        project = projects.get(ids.get(str(actor["blocking_item"]), -1))
        if project is not None and project not in visible:
            actor["blocking_item"] = None


__all__ = [
    "FRONTIER_BLOCKED_FIELDS",
    "HIDDEN_BLOCKER_WHY",
    "blocked_row",
    "compose_edge_why",
    "redact_next_actors",
]
