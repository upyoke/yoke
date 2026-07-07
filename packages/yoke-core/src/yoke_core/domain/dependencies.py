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
  ``status:done``, ``status:implemented``, or ``fact:merged``.
- **Rationale** is a human-readable explanation of why the edge exists.
- **Evidence JSON** is structured provenance payload.

Live dependency rows are canonical blockers; gate timing is expressed by
``gate_point`` and clearance is expressed by ``satisfaction``.

The type vocabulary (``GatePoint``, ``Satisfaction``, ``GateResult``,
``DependencyEdge``, and the private status sets) lives in the sibling
module :mod:`yoke_core.domain.dependency_types` and is re-exported
here for the stable public dependency API.

Dependencies:
    - An injected database connection for queries during evaluation.
"""

from __future__ import annotations

from typing import Any, List, Optional, Tuple

from yoke_core.domain import db_backend
from yoke_core.domain.dependency_types import (  # noqa: F401 — re-export public API
    DependencyEdge,
    GatePoint,
    GateResult,
    Satisfaction,
    _DONE_STATUSES,
    _IMPLEMENTED_STATUSES,
)


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


# ---------------------------------------------------------------------------
# Satisfaction evaluation
# ---------------------------------------------------------------------------


def evaluate_satisfaction(
    satisfaction: str,
    blocking_status: Optional[str],
    blocking_worktree: Optional[str] = None,
    blocking_merged: Optional[bool] = None,
) -> GateResult:
    """Evaluate whether a satisfaction condition holds for a blocking item.

    Args:
        satisfaction: The satisfaction condition string (e.g., ``"status:done"``).
        blocking_status: Current status of the blocking item (``None`` if unknown).
        blocking_worktree: Branch name of the blocking item's worktree (for
            ``fact:merged`` checks).
        blocking_merged: Pre-computed merge fact.  When ``True``, the caller
            has confirmed the blocker is merged (for example via
            ``items.merged_at`` or branch ancestry).  When ``None``, the
            caller has not confirmed the merge fact.

    Returns:
        A ``GateResult`` indicating whether the condition is met and why.
    """
    if satisfaction == Satisfaction.STATUS_DONE.value:
        if blocking_status in _DONE_STATUSES:
            return GateResult(True, "Blocking item has reached done.")
        return GateResult(
            False,
            f"Blocking item status is '{blocking_status}'; must reach done.",
        )

    if satisfaction == Satisfaction.STATUS_IMPLEMENTED.value:
        if blocking_status in _IMPLEMENTED_STATUSES:
            return GateResult(True, "Blocking item has reached implemented or later.")
        return GateResult(
            False,
            f"Blocking item status is '{blocking_status}'; must reach implemented.",
        )

    if satisfaction == Satisfaction.FACT_MERGED.value:
        if blocking_merged is True:
            return GateResult(True, "Blocking item's merge is confirmed.")
        if blocking_merged is False:
            branch_desc = f" ({blocking_worktree})" if blocking_worktree else ""
            return GateResult(
                False,
                f"Blocking item's branch{branch_desc} is not yet merged to main.",
            )
        # blocking_merged is None -- caller did not check; fall back to
        # status-based heuristic: release or done implies merge happened.
        if blocking_status in ("release", "done"):
            return GateResult(
                True,
                f"Blocking item status is '{blocking_status}' (merge inferred).",
            )
        return GateResult(
            False,
            f"Blocking item status is '{blocking_status}'; branch merge not confirmed.",
        )

    # Unknown satisfaction -- fail safe (unsatisfied)
    return GateResult(False, f"Unknown satisfaction condition: {satisfaction!r}")


# ---------------------------------------------------------------------------
# Gate-point-aware dependency queries
# ---------------------------------------------------------------------------

# SQL: Fetch unsatisfied dependencies at a specific gate point.
# Returns dependency metadata plus the blocking item's status and merge context.
# canonical schema -- no dependency_type or requires_merge columns.
_UNSATISFIED_DEPS_SQL = """
SELECT
    d.id,
    d.dependent_item,
    d.blocking_item,
    d.gate_point,
    d.satisfaction,
    d.rationale,
    bi.status AS blocking_status,
    bi.worktree AS blocking_worktree,
    bi.merged_at AS blocking_merged_at
FROM item_dependencies d
LEFT JOIN items bi ON bi.id = CAST(REPLACE(d.blocking_item, 'YOK-', '') AS INTEGER)
WHERE d.dependent_item = {p}
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
    cursor = conn.cursor()
    cursor.execute(
        _UNSATISFIED_DEPS_SQL.format(p=_p(conn)),
        (dependent_item, gate_point),
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
        ) = row
        edge = DependencyEdge(
            dep_id=dep_id,
            dependent_item=dep_item,
            blocking_item=blk_item,
            gate_point=gp,
            satisfaction=sat,
            rationale=rationale,
            blocking_status=blk_status,
            blocking_worktree=blk_worktree,
        )
        merge_fact = True if blk_merged_at else None
        result = evaluate_satisfaction(
            sat,
            blk_status,
            blk_worktree,
            blocking_merged=merge_fact,
        )
        if not result.satisfied:
            results.append((edge, result))

    return results


# ---------------------------------------------------------------------------
# Frontier-oriented batch query (used by frontier.py)
# ---------------------------------------------------------------------------

_FRONTIER_BLOCKS_SQL = """
SELECT
    d.dependent_item,
    d.blocking_item,
    d.gate_point,
    d.satisfaction,
    bi.status AS blocking_status,
    bi.worktree AS blocking_worktree,
    bi.merged_at AS blocking_merged_at
FROM item_dependencies d
LEFT JOIN items bi ON bi.id = CAST(REPLACE(d.blocking_item, 'YOK-', '') AS INTEGER)
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
    cursor.execute(_FRONTIER_BLOCKS_SQL.format(p=_p(conn)), (gate_point,))

    blocks: dict[str, list[tuple[str, str, str, str]]] = {}
    for dep_item, blk_item, gp, sat, blk_status, blk_worktree, blk_merged_at in cursor.fetchall():
        merge_fact = True if blk_merged_at else None
        result = evaluate_satisfaction(
            sat,
            blk_status,
            blk_worktree,
            blocking_merged=merge_fact,
        )
        if not result.satisfied:
            blocks.setdefault(dep_item, []).append(
                (blk_item, blk_status or "unknown", sat, result.reason)
            )

    return blocks


# ---------------------------------------------------------------------------
# Human-readable explanation
# ---------------------------------------------------------------------------


def explain_dependency(
    gate_point: str,
    satisfaction: str,
    blocking_item: str,
    blocking_status: Optional[str] = None,
    rationale: Optional[str] = None,
) -> str:
    """Generate a human-readable explanation of a dependency.

    Example output::

        blocks activation (satisfied when: status reaches done)
    """
    sat_desc = {
        "status:done": "status reaches done",
        "status:implemented": "status reaches implemented",
        "fact:merged": "branch is merged to main",
    }.get(satisfaction, satisfaction)

    gate_desc = {
        "activation": "blocks activation",
        "integration": "blocks integration (merge ordering)",
        "closure": "blocks closure",
    }.get(gate_point, f"blocks at {gate_point}")

    parts = [blocking_item, gate_desc, f"(satisfied when: {sat_desc})"]
    if blocking_status:
        parts.append(f"[current: {blocking_status}]")
    if rationale:
        parts.append(f"-- {rationale}")
    return " ".join(parts)
