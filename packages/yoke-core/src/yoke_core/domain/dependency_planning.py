"""Shared dependency-planning kernel.

The single lower-level planner that all gate consumers share. It answers
two questions for any requested ``gate_point``:

1. **Gate evaluation for one item**: which blockers are unsatisfied, why,
   and what condition satisfies them.
2. **Ordered planning for a candidate set**: which items are currently
   eligible, which are blocked, and what topological order the eligible
   items should follow.

Consumers: the frontier and scheduler (activation, start order); usher,
merge and deploy (integration, landing order); closeout (closure). Ordering
belongs here; WIP caps, ranking and claims belong to the consumers. Result
dataclasses live in :mod:`dependency_planning_results`; loops of waiting
items are found by :mod:`dependency_cycles`.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import db_backend
from .dependencies import GatePoint
from .dependency_planning_results import (
    BlockerDetail,
    CandidateItem,
    ItemGateEvaluation,
    PlanResult,
)
from .dependency_planning_telemetry import emit_batch_gate_evaluated
from .dependency_planning_order import topological_sort
from .dependency_satisfaction import (
    DeployedEnvironmentFact,
    evaluate_persisted_satisfaction,
    evaluate_satisfaction,
    read_deployed_environment_fact,
)
from .dependency_workflow_context import workflow_from_joined_values
from .frontier_workflow_versions import (
    FrontierWorkflowVersions,
    load_frontier_workflow_versions,
)
from .item_ref_columns import render_column_item_ref, resolve_column_item_ref
from .item_terminal_resources import terminal_stage_ids
from .item_worktree_resolution import primary_item_worktree_branch_sql


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _item_deps_sql(conn: Any) -> str:
    p = _p(conn)
    return f"""
SELECT d.id, d.dependent_item_id, d.blocking_item_id, d.gate_point, d.satisfaction,
       d.rationale, bi.status AS blocking_status,
       {primary_item_worktree_branch_sql("bi.id")} AS blocking_worktree,
       bi.merged_at AS blocking_merged_at,
       bi.workflow_id, bi.workflow_version_id, wv.version,
       wv.definition_json, wv.definition_digest, d.created_at
FROM item_dependencies d
LEFT JOIN items bi ON bi.id = d.blocking_item_id
LEFT JOIN workflow_versions wv ON wv.id = bi.workflow_version_id
WHERE d.dependent_item_id = {p} AND d.gate_point = {p}
"""


def _batch_deps_sql(
    conn: Any, project_ids: Optional[Sequence[int]], live_clause: str = ""
) -> str:
    p = _p(conn)
    holes = ", ".join(p for _ in project_ids or ()) or "NULL"
    scope = "" if project_ids is None else f" AND di.project_id IN ({holes})"
    return f"""
SELECT d.dependent_item_id, d.blocking_item_id, d.gate_point, d.satisfaction,
       d.rationale, bi.status AS blocking_status,
       {primary_item_worktree_branch_sql("bi.id")} AS blocking_worktree,
       bi.merged_at AS blocking_merged_at,
       bi.workflow_id, bi.workflow_version_id, d.id, d.created_at
FROM item_dependencies d
LEFT JOIN items di ON di.id = d.dependent_item_id
LEFT JOIN items bi ON bi.id = d.blocking_item_id
WHERE d.gate_point = {p}{scope}{live_clause}
"""


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

    resolved = resolve_column_item_ref(conn, item_id)
    if resolved is None:
        return ItemGateEvaluation(
            item_id=item_id,
            gate_point=gate_point,
            is_blocked=False,
            unsatisfied_blockers=[],
        )
    cursor = conn.cursor()
    cursor.execute(_item_deps_sql(conn), (resolved, gate_point))

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
            workflow_id,
            workflow_version_id,
            workflow_version,
            definition_json,
            definition_digest,
            dependency_created_at,
        ) = row

        merge_fact = True if blk_merged_at else None
        result = evaluate_persisted_satisfaction(
            conn,
            blocking_item_id=blk_item,
            satisfaction=sat,
            blocking_status=blk_status,
            blocking_worktree=blk_worktree,
            blocking_merged=merge_fact,
            blocking_merged_at=blk_merged_at,
            dependency_created_at=dependency_created_at,
            workflow=workflow_from_joined_values(
                workflow_id,
                workflow_version_id,
                workflow_version,
                definition_json,
                definition_digest,
            ),
        )

        if not result.satisfied:
            unsatisfied.append(
                BlockerDetail(
                    blocking_item=render_column_item_ref(conn, blk_item),
                    blocking_status=blk_status,
                    gate_point=gp,
                    satisfaction=sat,
                    rationale=rationale or "",
                    reason=result.reason,
                )
            )

    return ItemGateEvaluation(
        item_id=item_id,
        gate_point=gate_point,
        is_blocked=len(unsatisfied) > 0,
        unsatisfied_blockers=unsatisfied,
    )


def evaluate_batch_gates(
    conn: Any,
    gate_point: str,
    *,
    session_id: Optional[str] = None,
    project: Optional[str] = None,
    emit_events: bool = True,
    project_ids: Optional[Sequence[int]] = None,
    live_dependents: bool = False,
    versions: Optional[FrontierWorkflowVersions] = None,
) -> Dict[str, List[BlockerDetail]]:
    """Batch-evaluate all dependencies at a gate point. Returns a dict
    mapping ``dependent_item`` -> list of ``BlockerDetail`` for each item
    with unsatisfied blockers; items with no unsatisfied blockers are
    absent from the dict.

    ``emit_events=False`` suppresses the ``DependencyGateEvaluated``
    telemetry write so pure reads (e.g. a browser poll) leave no event
    rows behind; the default preserves emission for every existing caller.
    ``project_ids`` limits the read to edges whose dependent is in them.
    ``live_dependents`` leaves out edges whose dependent sits at a terminal
    stage of its pinned workflow: a finished item has nothing left to gate.
    Each workflow version is decoded once per call (``versions`` lends one
    the caller already read), and each deployed fact is read once per call.
    """
    GatePoint.from_db(gate_point)
    if versions is None:
        versions = load_frontier_workflow_versions(conn)
    live_clause, live_params = (
        versions.skip_clause(_p(conn), alias="di", statuses=terminal_stage_ids)
        if live_dependents
        else ("", [])
    )
    cursor = conn.cursor()
    cursor.execute(
        _batch_deps_sql(conn, project_ids, live_clause),
        (gate_point, *(project_ids or ()), *live_params),
    )

    blocks: Dict[str, List[BlockerDetail]] = {}
    deployed: Dict[Tuple[int, str], Optional[DeployedEnvironmentFact]] = {}
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
            workflow_id,
            workflow_version_id,
            dependency_id,
            dependency_created_at,
        ) = row

        if blk_item is not None and (blk_item, sat) not in deployed:
            deployed[(blk_item, sat)] = read_deployed_environment_fact(
                conn, blocking_item_id=int(blk_item), satisfaction=sat
            )
        result = evaluate_satisfaction(
            sat,
            blk_status,
            blk_worktree,
            True if blk_merged_at else None,
            deployed.get((blk_item, sat)),
            workflow=None
            if workflow_version_id is None
            else versions.runtime_for(
                conn,
                {"workflow_id": workflow_id, "workflow_version_id": workflow_version_id},
            ),
            blocking_merged_at=blk_merged_at,
            dependency_created_at=dependency_created_at,
        )

        if not result.satisfied:
            detail = BlockerDetail(
                dependency_id=int(dependency_id),
                blocking_item=render_column_item_ref(conn, blk_item),
                blocking_status=blk_status,
                gate_point=gp,
                satisfaction=sat,
                rationale=rationale or "",
                reason=result.reason,
            )
            blocks.setdefault(render_column_item_ref(conn, dep_item), []).append(detail)

    # Emit DependencyGateEvaluated batch summary
    if emit_events:
        emit_batch_gate_evaluated(
            gate_point,
            total_rows,
            blocks,
            session_id=session_id,
            project=project,
        )

    return blocks


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
            blocked.append(
                CandidateItem(
                    item_id=item_id,
                    is_eligible=False,
                    blockers=blockers,
                )
            )
        else:
            eligible.append(item_id)

    # Build ordering edges from ALL deps at this gate point
    # (not just unsatisfied — satisfied deps still define order among eligible items)
    cursor = conn.cursor()
    cursor.execute(_batch_deps_sql(conn, None), (gate_point,))
    ordering_edges: List[Tuple[str, str]] = []
    for row in cursor.fetchall():
        dep_item = row[0]
        blk_item = row[1]
        if dep_item in candidate_set and blk_item in candidate_set:
            # Edge: blocker should come before dependent
            ordering_edges.append((blk_item, dep_item))

    # Topological sort of eligible items
    ordered, cycle_items = topological_sort(eligible, ordering_edges)

    return PlanResult(
        gate_point=gate_point,
        eligible=ordered,
        blocked=blocked,
        has_cycle=len(cycle_items) > 0,
        cycle_items=cycle_items,
    )
