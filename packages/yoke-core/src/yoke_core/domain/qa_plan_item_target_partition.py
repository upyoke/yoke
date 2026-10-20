"""Item plan runs skip cases passed at the candidate, then run one target at a time.

One item transition can carry cases on different execution targets: a
no-target CI case beside a mission against production. An execution has one
immutable target, so a mixed roster used to refuse outright, even when every
case on the other target had already passed on the exact candidate commit.

Item mode now leaves out each requirement whose newest run passed at the
item's candidate commit (the primary lane's recorded head) and still proves
the live method config and target, whether ``yoke qa plan run`` or
``yoke qa case run`` recorded it. The open rows are split by execution
target in roster order. One execution runs the first target that still owes
a case; the rest count as remaining, and the next ``yoke qa plan run``
begins the next target. A live execution keeps its own immutable roster.
"""

from __future__ import annotations

from typing import Any, Callable

from yoke_core.domain.item_worktrees import primary_item_worktree
from yoke_core.domain.qa_latest_execution import latest_executions
from yoke_core.domain.qa_merging_identity import recorded_head_sha
from yoke_core.domain.qa_plan_execution_store import (
    QaPlanExecutionStateError,
    live_plan_execution_id,
    select_plan_execution,
)
from yoke_core.domain.qa_requirement_pass_currency import (
    current_passing_requirements,
)

Settle = Callable[
    [list[dict[str, Any]]], tuple[dict[str, Any] | None, list[dict[str, Any]]]
]
ROSTER_PASSED_CODE = "qa_plan_roster_passed_at_candidate"


def candidate_passed_requirements(
    conn: Any, roster: list[dict[str, Any]], *, item_id: int
) -> tuple[str, set[int]]:
    """The candidate commit and the roster requirements already passed there."""
    lane = primary_item_worktree(conn, int(item_id)) or {}
    candidate = str(lane.get("commit_sha") or "").strip()
    if not candidate:
        return "", set()
    current = current_passing_requirements(
        conn, [int(row["requirement_id"]) for row in roster]
    )
    latest = latest_executions(conn, current)
    return candidate, {
        requirement_id
        for requirement_id in current
        if requirement_id in latest
        and recorded_head_sha(latest[requirement_id]["raw_result"]) == candidate
    }


def _numbered(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{**row, "ordinal": ordinal} for ordinal, row in enumerate(rows)]


def item_target_partition(
    conn: Any,
    roster: list[dict[str, Any]],
    *,
    item_id: int,
    transition_id: str,
    settle: Settle,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]], int]:
    """Return (settled reprint, one-target roster, remaining requirement count)."""
    candidate, passed = candidate_passed_requirements(conn, roster, item_id=item_id)
    live_id = live_plan_execution_id(
        conn, item_id=int(item_id), transition_id=str(transition_id)
    )
    if live_id is not None:
        live = select_plan_execution(conn, live_id, lock=False)
        ids = {int(row["requirement_id"]) for row in live["roster"]}
        group = [row for row in roster if int(row["requirement_id"]) in ids]
        others = [
            row for row in roster if int(row["requirement_id"]) not in ids | passed
        ]
        reprint, kept = settle(_numbered(group))
        return reprint, kept, len(others)
    open_rows = [row for row in roster if int(row["requirement_id"]) not in passed]
    if not open_rows:
        raise QaPlanExecutionStateError(
            f"{ROSTER_PASSED_CODE}: every requirement for this item transition "
            f"{transition_id!r} already passed at candidate {candidate}, so the "
            "plan has nothing left to run. Read the results with `yoke qa "
            "requirement list --item ITEM`. To prove a newer change, commit it "
            "to the lane first; to repeat one case, run `yoke qa case run "
            "--requirement-id ID`."
        )
    from yoke_core.domain.qa_plan_chain_hosts import chain_host_groups

    chains = chain_host_groups(open_rows)
    groups: dict[tuple[str, int | None], list[dict[str, Any]]] = {}
    for row in open_rows:
        key = (
            str(row.get("execution_target_digest") or ""),
            chains[int(row["requirement_id"])][2],
        )
        groups.setdefault(key, []).append(row)
    first_reprint = None
    ordered = list(groups.values())
    for index, rows in enumerate(ordered):
        reprint, kept = settle(_numbered(rows))
        if kept:
            later = sum(len(group) for group in ordered[index + 1 :])
            return None, kept, later
        first_reprint = first_reprint or reprint
    return first_reprint, [], 0


__all__ = [
    "ROSTER_PASSED_CODE",
    "candidate_passed_requirements",
    "item_target_partition",
]
