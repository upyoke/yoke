"""Clear the plan positions written onto plan-less admitted QA copies.

Deployment admission copies a member's own frozen post-deploy obligations
onto the stage subject as plan-less ``qa_requirements`` rows. The
materializer stamped a ``case_position`` and ``baseline_position`` onto
each copy, which no plan-less row may carry: only a plan assigns positions,
and the roster selection gives a plan-less case its order when it builds
(``qa_plan_execution_roster.ordered_plan_requirements``). The drift check
every execution begin runs (``machine_qa_plan_case_snapshot.case_positions``)
reads a number there as "this requirement joined a plan after the roster
froze" and refuses the case -- permanently, because the rebuilt roster of an
abort-and-restart reads the same row back.

So the copies already written are unrunnable on the ``agent_mission`` and
``host_control`` runners until their positions go away. This entry clears
exactly those: a row belonging to no plan that carries either position. It
is scoped by that shape rather than by the admission case-key prefix or by
a creation timestamp, because the shape IS the invariant both readers
state, and nothing else ever writes a position onto a plan-less row --
snapshot convergence fills positions only for rows that have a plan.

Idempotent against its own output already existing, not merely against
having run: the build that carries this entry writes NULL on both columns,
so a copy created while the entry sits unapplied is already in the state
the entry produces and the predicate simply does not match it. No surface
is removed and no reader breaks -- the roster and the drift check both
already treat a plan-less NULL as the normal case -- so this needs no
``MINIMUM_SERVING_VERSION``.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.schema_common import _table_exists

REQUIREMENT_TABLE = "qa_requirements"

#: A plan-less row that carries either position. Both columns are cleared
#: together: a half-positioned row is the same contradiction as a fully
#: positioned one, and the drift check refuses on either.
_MISPOSITIONED = (
    f"FROM {REQUIREMENT_TABLE} WHERE plan_id IS NULL "
    "AND (case_position IS NOT NULL OR baseline_position IS NOT NULL)"
)


def apply(conn: Any) -> None:
    """Drop the positions from every QA requirement that belongs to no plan."""
    if not _table_exists(conn, REQUIREMENT_TABLE):
        return
    conn.execute(
        f"UPDATE {REQUIREMENT_TABLE} "
        "SET case_position=NULL, baseline_position=NULL "
        "WHERE plan_id IS NULL "
        "AND (case_position IS NOT NULL OR baseline_position IS NOT NULL)"
    )


def invariants(conn: Any) -> None:
    """Prove no QA requirement holds a position without a plan behind it."""
    if not _table_exists(conn, REQUIREMENT_TABLE):
        return
    row = conn.execute(f"SELECT COUNT(*) {_MISPOSITIONED}").fetchone()
    remaining = int(row[0]) if row is not None else 0
    assert remaining == 0, (
        f"{REQUIREMENT_TABLE} still holds {remaining} plan-less row(s) with a "
        "case_position or baseline_position; only a plan assigns positions, "
        "and a plan-less row carrying one is refused by every execution begin"
    )


__all__ = ["REQUIREMENT_TABLE", "apply", "invariants"]
