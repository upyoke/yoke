"""First-class dependency gate semantics for the Yoke core.

This module is the shared source of truth for dependency gate points
and satisfaction conditions.  It provides the canonical vocabulary for
the blocker-only dependency model where every row in ``item_dependencies``
is a real enforced blocker.

Key concepts:

- **Gate point** describes *when* the dependency matters in the
  dependent item's lifecycle: ``activation`` (don't start),
  ``integration`` (work in parallel but land later), or ``closure``
  (don't close until blocker reaches a milestone).
- **Satisfaction condition** describes *what* must be true about the
  blocking item for the dependency to be considered resolved:
  ``status:done``, ``status:implemented``, ``fact:merged``, or
  ``fact:deployed:<environment-name>``.
- **Rationale** is a human-readable explanation of why the edge exists.
- **Evidence JSON** is structured provenance payload.

Live dependency rows are canonical blockers; gate timing is expressed by
``gate_point`` and clearance is expressed by ``satisfaction``.

The type vocabulary (``GatePoint``, ``Satisfaction``, ``GateResult``,
and ``DependencyEdge``) lives in the sibling
module :mod:`yoke_core.domain.dependency_types` and is re-exported
here for the stable public dependency API.

Dependencies:
    - An injected database connection for queries during evaluation.
"""

from __future__ import annotations

from typing import Any, List, Tuple

from yoke_core.domain import db_backend
from yoke_core.domain.dependency_types import (  # noqa: F401 — re-export public API
    DependencyEdge,
    GatePoint,
    GateResult,
    Satisfaction,
)
from yoke_core.domain.dependency_explanation import (  # noqa: F401 — public API
    explain_dependency,
)
from yoke_core.domain.dependency_satisfaction import (
    evaluate_persisted_satisfaction,
    evaluate_satisfaction,  # noqa: F401 — re-export public API
)
from yoke_core.domain.dependency_workflow_context import (
    workflow_from_joined_values,
)
from yoke_core.domain.item_ref_columns import (
    render_column_item_ref,
    resolve_column_item_ref,
)
from yoke_core.domain.item_worktree_resolution import (
    primary_item_worktree_branch_sql,
)


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


# ---------------------------------------------------------------------------
# Gate-point-aware dependency queries
# ---------------------------------------------------------------------------

# SQL: Fetch unsatisfied dependencies at a specific gate point.
# Returns dependency metadata plus the blocking item's status and merge context.
# canonical schema -- no dependency_type or requires_merge columns.
_UNSATISFIED_DEPS_SQL = """
SELECT
    d.id,
    d.dependent_item_id,
    d.blocking_item_id,
    d.gate_point,
    d.satisfaction,
    d.rationale,
    bi.status AS blocking_status,
    {blocking_worktree_sql} AS blocking_worktree,
    bi.merged_at AS blocking_merged_at,
    bi.workflow_id,
    bi.workflow_version_id,
    wv.version,
    wv.definition_json,
    wv.definition_digest
FROM item_dependencies d
LEFT JOIN items bi ON bi.id = d.blocking_item_id
LEFT JOIN workflow_versions wv ON wv.id = bi.workflow_version_id
WHERE d.dependent_item_id = {p}
  AND d.gate_point = {p}
"""


def query_unsatisfied_at_gate(
    conn: Any,
    dependent_item: str,
    gate_point: str,
) -> List[Tuple[DependencyEdge, GateResult]]:
    """Query and evaluate dependencies at a specific gate point.

    Returns only *unsatisfied* dependencies -- those whose satisfaction
    condition is not met by the blocking item's current state.

    Args:
        conn: Database connection.
        dependent_item: Canonical ``YOK-N`` identifier.
        gate_point: One of ``activation``, ``integration``, ``closure``.

    Returns:
        List of ``(DependencyEdge, GateResult)`` for each unsatisfied dep.
    """
    resolved = resolve_column_item_ref(conn, dependent_item)
    if resolved is None:
        return []
    cursor = conn.cursor()
    cursor.execute(
        _UNSATISFIED_DEPS_SQL.format(
            p=_p(conn),
            blocking_worktree_sql=primary_item_worktree_branch_sql("bi.id"),
        ),
        (resolved, gate_point),
    )
    results: List[Tuple[DependencyEdge, GateResult]] = []

    for row in cursor.fetchall():
        (
            dep_id,
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
            workflow_version,
            definition_json,
            definition_digest,
        ) = row
        edge = DependencyEdge(
            dep_id=dep_id,
            dependent_item=render_column_item_ref(conn, dep_item),
            blocking_item=render_column_item_ref(conn, blk_item),
            gate_point=gp,
            satisfaction=sat,
            rationale=rationale,
            blocking_status=blk_status,
            blocking_worktree=blk_worktree,
        )
        merge_fact = True if blk_merged_at else None
        result = evaluate_persisted_satisfaction(
            conn,
            blocking_item_id=blk_item,
            satisfaction=sat,
            blocking_status=blk_status,
            blocking_worktree=blk_worktree,
            blocking_merged=merge_fact,
            workflow=workflow_from_joined_values(
                workflow_id,
                workflow_version_id,
                workflow_version,
                definition_json,
                definition_digest,
            ),
        )
        if not result.satisfied:
            results.append((edge, result))

    return results


# ---------------------------------------------------------------------------
# Frontier-oriented batch query (used by frontier.py)
# ---------------------------------------------------------------------------

_FRONTIER_BLOCKS_SQL = """
SELECT
    d.dependent_item_id,
    d.blocking_item_id,
    d.gate_point,
    d.satisfaction,
    bi.status AS blocking_status,
    {blocking_worktree_sql} AS blocking_worktree,
    bi.merged_at AS blocking_merged_at,
    bi.workflow_id,
    bi.workflow_version_id,
    wv.version,
    wv.definition_json,
    wv.definition_digest
FROM item_dependencies d
LEFT JOIN items bi ON bi.id = d.blocking_item_id
LEFT JOIN workflow_versions wv ON wv.id = bi.workflow_version_id
WHERE d.gate_point = {p}
"""


def query_frontier_blocks(
    conn: Any,
    gate_point: str = "activation",
) -> dict[str, list[tuple[str, str, str, str]]]:
    """Batch-query unsatisfied blocking deps for frontier computation.

    Returns a dict mapping dependent_item -> list of
    ``(blocking_item, blocking_status, satisfaction, reason)`` for
    each unsatisfied blocker.

    Only returns *unsatisfied* dependencies.
    """
    cursor = conn.cursor()
    cursor.execute(
        _FRONTIER_BLOCKS_SQL.format(
            p=_p(conn),
            blocking_worktree_sql=primary_item_worktree_branch_sql("bi.id"),
        ),
        (gate_point,),
    )

    blocks: dict[str, list[tuple[str, str, str, str]]] = {}
    for row in cursor.fetchall():
        (
            dep_item,
            blk_item,
            gp,
            sat,
            blk_status,
            blk_worktree,
            blk_merged_at,
            workflow_id,
            workflow_version_id,
            workflow_version,
            definition_json,
            definition_digest,
        ) = row
        merge_fact = True if blk_merged_at else None
        result = evaluate_persisted_satisfaction(
            conn,
            blocking_item_id=blk_item,
            satisfaction=sat,
            blocking_status=blk_status,
            blocking_worktree=blk_worktree,
            blocking_merged=merge_fact,
            workflow=workflow_from_joined_values(
                workflow_id,
                workflow_version_id,
                workflow_version,
                definition_json,
                definition_digest,
            ),
        )
        if not result.satisfied:
            blocks.setdefault(render_column_item_ref(conn, dep_item), []).append(
                (
                    render_column_item_ref(conn, blk_item),
                    blk_status or "unknown",
                    sat,
                    result.reason,
                )
            )

    return blocks
