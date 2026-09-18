"""Prove one roster case still matches the requirement row it was taken from.

A QA plan execution freezes its roster, and every later begin/submit re-reads
the live requirement to prove nothing moved underneath it. The positions are
the subtle part: only a case that belongs to a plan carries positions of its
own, because only a plan assigns them. A plan-less case — an item's own
requirement admitted into a deployment stage, or any directly authored case —
was given its order by the selection that built the roster
(:func:`qa_plan_execution_roster.ordered_plan_requirements`), and its row
holds no position at all. So the drift check honours the same rule the
selection used, and a row that has since gained or lost a plan is reported as
the drift it is rather than read as a missing number.
"""

from __future__ import annotations

from typing import Any, Mapping

from yoke_core.domain.qa_plan_execution_store import QaPlanExecutionStateError


def case_positions(
    case: Mapping[str, Any],
    row: Mapping[str, Any],
) -> tuple[int, int]:
    """Return the live positions to compare against the frozen roster case.

    *row* is the requirement's own ``case_position`` / ``baseline_position``,
    either of which is null for a plan-less case.
    """
    requirement_id = int(case["requirement_id"])
    live = (row["case_position"], row["baseline_position"])
    if case.get("plan_id") is None:
        if any(value is not None for value in live):
            raise QaPlanExecutionStateError(
                f"QA requirement {requirement_id} joined a plan after this "
                "execution froze its roster, so the order it is being run in "
                "is no longer the order the plan assigns. Abort this "
                "execution with `yoke qa plan abort` and start a new one, "
                "which rebuilds the roster from the current requirements."
            )
        return int(case["case_position"]), int(case["baseline_position"])
    if any(value is None for value in live):
        raise QaPlanExecutionStateError(
            f"QA requirement {requirement_id} lost the plan positions this "
            "execution froze, so its place in the roster can no longer be "
            "proved. Abort this execution with `yoke qa plan abort`, "
            "re-materialize the plan, and start a new one."
        )
    return int(live[0]), int(live[1])


__all__ = ["case_positions"]
