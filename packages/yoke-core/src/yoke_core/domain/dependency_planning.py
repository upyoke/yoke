"""Shared dependency-planning kernel.

The single lower-level planner that all gate consumers share. It answers
two questions for any requested ``gate_point``:

1. **Gate evaluation for one item**: which blockers are unsatisfied, why,
   and what condition satisfies them.
2. **Ordered planning for a candidate set**: which items are currently
   eligible, which are blocked, and what topological order the eligible
   items should follow.

Consumers: ``frontier.py`` / ``scheduler.py`` (activation view, start
order); usher / merge / deploy (integration view, landing order);
``closure`` is reserved as the future closeout gate.

This module owns planning logic (evaluation + ordering). Orchestration
(WIP caps, ranking heuristics, claim management) lives in the consuming
modules. Result dataclasses live in
``yoke_core.domain.dependency_planning_results`` and are re-exported
here for stability.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from . import db_backend
from .dependencies import (
    DependencyEdge,
    GatePoint,
    GateResult,
    Satisfaction,
    evaluate_satisfaction,
)
from .dependency_planning_results import (
    BlockerDetail,
    CandidateItem,
    ItemGateEvaluation,
    PlanResult,
)


# --- SQL queries ---

def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _item_deps_sql(conn: Any) -> str:
    p = _p(conn)
    return f"""
SELECT d.id, d.dependent_item, d.blocking_item, d.gate_point, d.satisfaction,
       d.rationale, bi.status AS blocking_status,
       bi.worktree AS blocking_worktree, bi.merged_at AS blocking_merged_at
FROM item_dependencies d
LEFT JOIN items bi ON bi.id = CAST(REPLACE(d.blocking_item, 'YOK-', '') AS INTEGER)
WHERE d.dependent_item = {p} AND d.gate_point = {p}
"""


def _batch_deps_sql(conn: Any) -> str:
    p = _p(conn)
    return f"""
SELECT d.dependent_item, d.blocking_item, d.gate_point, d.satisfaction,
       d.rationale, bi.status AS blocking_status,
       bi.worktree AS blocking_worktree, bi.merged_at AS blocking_merged_at
FROM item_dependencies d
LEFT JOIN items bi ON bi.id = CAST(REPLACE(d.blocking_item, 'YOK-', '') AS INTEGER)
WHERE d.gate_point = {p}
"""


# --- Single-item gate evaluation ---


def evaluate_item_gate(
    conn: Any,
    item_id: str,
    gate_point: str,
) -> ItemGateEvaluation:
    """Evaluate all dependencies for one item at a specific gate point.

    Returns an ``ItemGateEvaluation`` with structured blocker details
    for each unsatisfied dependency. Supported gate_points:
    ``activation``, ``integration``, ``closure``.
    """
    # Validate gate_point
    GatePoint.from_db(gate_point)

    cursor = conn.cursor()
    cursor.execute(_item_deps_sql(conn), (item_id, gate_point))

    unsatisfied: List[BlockerDetail] = []
    for row in cursor.fetchall():
        (
            _dep_id,
            _dep_item,
            blk_item,
            gp,
            sat,
            rationale,
            blk_status,
            blk_worktree,
            blk_merged_at,
        ) = row

        merge_fact = True if blk_merged_at else None
        result = evaluate_satisfaction(
            sat,
            blk_status,
            blk_worktree,
            blocking_merged=merge_fact,
        )

        if not result.satisfied:
            unsatisfied.append(BlockerDetail(
                blocking_item=blk_item,
                blocking_status=blk_status,
                gate_point=gp,
                satisfaction=sat,
                rationale=rationale or "",
                reason=result.reason,
            ))

    return ItemGateEvaluation(
        item_id=item_id,
        gate_point=gate_point,
        is_blocked=len(unsatisfied) > 0,
        unsatisfied_blockers=unsatisfied,
    )


# --- Batch gate evaluation (frontier-oriented) ---


def evaluate_batch_gates(
    conn: Any,
    gate_point: str,
    *,
    session_id: Optional[str] = None,
    project: Optional[str] = None,
    emit_events: bool = True,
) -> Dict[str, List[BlockerDetail]]:
    """Batch-evaluate all dependencies at a gate point. Returns a dict
    mapping ``dependent_item`` -> list of ``BlockerDetail`` for each item
    with unsatisfied blockers; items with no unsatisfied blockers are
    absent from the dict.

    ``emit_events=False`` suppresses the ``DependencyGateEvaluated``
    telemetry write so pure reads (e.g. a browser poll) leave no event
    rows behind; the default preserves emission for every existing caller.
    """
    GatePoint.from_db(gate_point)

    cursor = conn.cursor()
    cursor.execute(_batch_deps_sql(conn), (gate_point,))

    blocks: Dict[str, List[BlockerDetail]] = {}
    all_rows = cursor.fetchall()
    total_rows = len(all_rows)
    for row in all_rows:
        (
            dep_item,
            blk_item,
            gp,
            sat,
            rationale,
            blk_status,
            blk_worktree,
            blk_merged_at,
        ) = row

        merge_fact = True if blk_merged_at else None
        result = evaluate_satisfaction(
            sat,
            blk_status,
            blk_worktree,
            blocking_merged=merge_fact,
        )

        if not result.satisfied:
            detail = BlockerDetail(
                blocking_item=blk_item,
                blocking_status=blk_status,
                gate_point=gp,
                satisfaction=sat,
                rationale=rationale or "",
                reason=result.reason,
            )
            blocks.setdefault(dep_item, []).append(detail)

    # Emit DependencyGateEvaluated batch summary
    if emit_events:
        _emit_batch_gate_evaluated(
            gate_point,
            total_rows,
            blocks,
            session_id=session_id,
            project=project,
        )

    return blocks


# --- Topological ordering ---


def _topological_sort(
    items: List[str],
    edges: List[Tuple[str, str]],
) -> Tuple[List[str], List[str]]:
    """Kahn's topological sort. ``edges`` are (blocker, dependent) pairs;
    blocker must come before dependent. Returns
    ``(ordered_items, cycle_items)`` — if ``cycle_items`` is non-empty the
    sort was incomplete.
    """
    item_set = set(items)
    # Only consider edges between items in the candidate set
    relevant_edges = [(b, d) for b, d in edges if b in item_set and d in item_set]

    # Build adjacency and in-degree
    adj: Dict[str, List[str]] = {i: [] for i in items}
    in_degree: Dict[str, int] = {i: 0 for i in items}
    for blocker, dependent in relevant_edges:
        adj[blocker].append(dependent)
        in_degree[dependent] = in_degree.get(dependent, 0) + 1

    # Initialize queue with zero in-degree items
    queue = sorted([i for i in items if in_degree[i] == 0])
    ordered: List[str] = []

    while queue:
        node = queue.pop(0)
        ordered.append(node)
        for neighbor in sorted(adj.get(node, [])):
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)
        queue.sort()  # deterministic

    cycle_items = [i for i in items if i not in set(ordered)]
    return ordered, cycle_items


# --- Candidate-set planning ---


def plan_candidate_set(
    conn: Any,
    candidate_ids: List[str],
    gate_point: str,
) -> PlanResult:
    """Plan a candidate set at a specific gate point.

    Evaluates each candidate's dependencies, partitions into eligible
    vs blocked, and returns the eligible items in topological order
    (dependencies first). Supported gate_points: ``activation``,
    ``integration``, ``closure``.
    """
    GatePoint.from_db(gate_point)

    if not candidate_ids:
        return PlanResult(gate_point=gate_point)

    # Batch-evaluate all dependencies at this gate point
    all_blocks = evaluate_batch_gates(conn, gate_point)

    candidate_set = set(candidate_ids)
    eligible: List[str] = []
    blocked: List[CandidateItem] = []

    for item_id in candidate_ids:
        blockers = all_blocks.get(item_id, [])
        if blockers:
            blocked.append(CandidateItem(
                item_id=item_id,
                is_eligible=False,
                blockers=blockers,
            ))
        else:
            eligible.append(item_id)

    # Build ordering edges from ALL deps at this gate point
    # (not just unsatisfied — satisfied deps still define order among eligible items)
    cursor = conn.cursor()
    cursor.execute(_batch_deps_sql(conn), (gate_point,))
    ordering_edges: List[Tuple[str, str]] = []
    for row in cursor.fetchall():
        dep_item = row[0]
        blk_item = row[1]
        if dep_item in candidate_set and blk_item in candidate_set:
            # Edge: blocker should come before dependent
            ordering_edges.append((blk_item, dep_item))

    # Topological sort of eligible items
    ordered, cycle_items = _topological_sort(eligible, ordering_edges)

    return PlanResult(
        gate_point=gate_point,
        eligible=ordered,
        blocked=blocked,
        has_cycle=len(cycle_items) > 0,
        cycle_items=cycle_items,
    )


# --- Telemetry: DependencyGateEvaluated ---

_logger = logging.getLogger(__name__)


def _emit_batch_gate_evaluated(
    gate_point: str,
    total_rows: int,
    blocks: Dict[str, List[BlockerDetail]],
    *,
    session_id: Optional[str] = None,
    project: Optional[str] = None,
) -> None:
    """Emit a batch summary event for dependency gate evaluation."""
    try:
        from .events import emit_event

        unsatisfied_count = sum(len(v) for v in blocks.values())
        unsatisfied_summary = []
        for dep_item, details in blocks.items():
            for d in details:
                unsatisfied_summary.append({
                    "item_id": dep_item,
                    "blocking_item": d.blocking_item,
                    "gate_point": d.gate_point,
                    "satisfaction": d.satisfaction,
                    "reason": d.reason,
                    "rationale": d.rationale,
                })

        emit_event(
            "DependencyGateEvaluated",
            event_kind="workflow",
            event_type="dependency_gate",
            source_type="backend",
            session_id=session_id or "",
            project=project or "yoke",
            context={
                "gate_point": gate_point,
                "total_rows_evaluated": total_rows,
                "unsatisfied_count": unsatisfied_count,
                "blocked_item_count": len(blocks),
                "unsatisfied_summary": unsatisfied_summary[:20],
            },
        )
    except Exception as exc:
        _logger.debug("DependencyGateEvaluated emission failed: %s", exc)
