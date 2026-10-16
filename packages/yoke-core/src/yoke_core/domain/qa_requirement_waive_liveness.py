"""A waiver only reaches a requirement that still counts.

A retracted, superseded or replaced row is already settled: gates never grade
it, so waiving it would report success while changing nothing. The refusal
names why the row no longer counts and the live copy to waive instead, when
one exists, so the operator re-targets the waiver rather than trusting a no-op.
"""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain.db_helpers import query_one

NOT_LIVE_CODE = "requirement_not_live"


class RequirementNotLiveError(ValueError):
    """The requirement no longer counts; the message names its current copy."""


def _current_copy(conn: Any, row: dict[str, Any]) -> Optional[int]:
    """The successor link, else the newest live copy of the same plan case."""
    for column in ("superseded_by_requirement_id", "replacement_requirement_id"):
        if row.get(column):
            return int(row[column])
    if row.get("plan_id") is None:
        return None
    copy = query_one(
        conn,
        "SELECT id FROM qa_requirements WHERE id<>%s AND plan_id=%s "
        "AND plan_case_key IS NOT DISTINCT FROM %s "
        "AND COALESCE(deployment_member_item_id, item_id) IS NOT DISTINCT FROM %s "
        "AND qa_phase=%s AND host_baseline IS NOT DISTINCT FROM %s "
        "AND target_env IS NOT DISTINCT FROM %s AND retracted_at IS NULL "
        "AND superseded_by_requirement_id IS NULL "
        "AND replacement_requirement_id IS NULL ORDER BY id DESC LIMIT 1",
        (
            int(row["id"]),
            int(row["plan_id"]),
            row["plan_case_key"],
            row["subject_item_id"],
            row["qa_phase"],
            row["host_baseline"],
            row["target_env"],
        ),
    )
    return int(copy["id"]) if copy is not None else None


def require_live_for_waiver(conn: Any, req_id: int) -> None:
    """Refuse a waiver on a row that no longer counts, naming its current copy."""
    row = query_one(
        conn,
        "SELECT id, plan_id, plan_case_key, qa_phase, host_baseline, target_env, "
        "COALESCE(deployment_member_item_id, item_id) AS subject_item_id, "
        "retracted_at, retraction_rationale, superseded_at, "
        "superseded_by_requirement_id, replacement_requirement_id "
        "FROM qa_requirements WHERE id=%s",
        (int(req_id),),
    )
    if row is None:
        return
    row = dict(row)
    if row["retracted_at"] is not None:
        state = f"was retracted ({row['retraction_rationale'] or 'no rationale'})"
    elif row["superseded_by_requirement_id"] or row["superseded_at"] is not None:
        state = "was superseded"
    elif row["replacement_requirement_id"]:
        state = "was replaced by a corrected case"
    else:
        return
    current = _current_copy(conn, row)
    target = (
        f"Waive its current copy instead: yoke qa requirement waive "
        f"--requirement-id {current} --rationale R."
        if current is not None
        else "No live copy of this case exists, so nothing is left to waive."
    )
    raise RequirementNotLiveError(
        f"{NOT_LIVE_CODE}: requirement {req_id} {state}, so it no longer counts "
        f"toward any gate and a waiver would change nothing. {target}"
    )


__all__ = [
    "NOT_LIVE_CODE",
    "RequirementNotLiveError",
    "require_live_for_waiver",
]
