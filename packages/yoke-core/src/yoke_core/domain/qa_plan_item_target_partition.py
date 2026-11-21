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
begins the next target. A live execution keeps its own immutable roster;
a request that shares no requirement with it refuses with
``qa_single_case_scope_busy`` and names the command that ends it.
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
from yoke_core.domain.qa_plan_case_chain import settled_chain_tails
from yoke_core.domain.qa_requirement_pass_currency import (
    current_passing_requirements,
)

Settle = Callable[
    [list[dict[str, Any]]], tuple[dict[str, Any] | None, list[dict[str, Any]]]
]
ROSTER_PASSED_CODE = "qa_plan_roster_passed_at_candidate"
SCOPE_BUSY_CODE = "qa_single_case_scope_busy"
RESUMABLE_STATES = frozenset({"active", "waiting", "walking"})


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


def _ending_command(conn: Any, live: dict[str, Any], requirement_ids: list[int]) -> str:
    """The command that moves ``live`` toward its end, by state."""
    from yoke_core.domain.project_identity import render_item_ref

    execution_id = str(live["id"])
    item_ref = render_item_ref(conn, int(live["item_id"]))
    if live["state"] == "awaiting_walk_review":
        return (
            f"review it with `yoke qa plan review-begin --item {item_ref} "
            f"--execution-id {execution_id}`, then the `yoke qa plan "
            "review-submit` command it prints"
        )
    if live["state"] in RESUMABLE_STATES:
        resume = (
            f"yoke qa case run --requirement-id {requirement_ids[0]}"
            if len(requirement_ids) == 1
            else f"yoke qa plan run --item {item_ref} "
            f"--transition {live['transition_id']}"
        )
        return f"resume it with `{resume}`"
    return "finish it"


def _scope_busy(conn: Any, live: dict[str, Any]) -> QaPlanExecutionStateError:
    requirement_ids = [int(row["requirement_id"]) for row in live["roster"]]
    from yoke_core.domain.qa_plan_execution_roster_change import abort_command

    return QaPlanExecutionStateError(
        f"{SCOPE_BUSY_CODE}: execution {live['id']} ({live['state']}) is live on "
        f"this item transition for requirement "
        f"{', '.join(str(i) for i in requirement_ids)}, and a transition holds "
        f"one live execution at a time. {_ending_command(conn, live, requirement_ids)}"
        f", or end it with `{abort_command(conn, live)}`; then retry."
    )


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
    passed = settled_chain_tails(roster, passed)
    live_id = live_plan_execution_id(
        conn, item_id=int(item_id), transition_id=str(transition_id)
    )
    if live_id is not None:
        live = select_plan_execution(conn, live_id, lock=False)
        ids = {int(row["requirement_id"]) for row in live["roster"]}
        group = [row for row in roster if int(row["requirement_id"]) in ids]
        if not group:
            raise _scope_busy(conn, live)
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
    host_free = (None, (), None, None)
    default_hosts = {}
    for row in open_rows:
        host_group = chains[int(row["requirement_id"])]
        if host_group != host_free and host_group[2] is None:
            default_hosts.setdefault(str(row.get("execution_target_digest") or ""), host_group)
    groups_by_target = {}
    for row in open_rows:
        digest = str(row.get("execution_target_digest") or "")
        host_group = chains[int(row["requirement_id"])]
        if host_group == host_free:
            host_group = default_hosts.get(digest, host_free)
        groups = groups_by_target.setdefault(digest, [])
        if not groups or groups[-1][0] != host_group:
            groups.append((host_group, []))
        groups[-1][1].append(row)
    first_reprint = None
    ordered = [rows for groups in groups_by_target.values() for _, rows in groups]
    for index, rows in enumerate(ordered):
        reprint, kept = settle(_numbered(rows))
        if kept:
            later = sum(len(group) for group in ordered[index + 1 :])
            return None, kept, later
        first_reprint = first_reprint or reprint
    return first_reprint, [], 0


__all__ = [
    "ROSTER_PASSED_CODE",
    "SCOPE_BUSY_CODE",
    "candidate_passed_requirements",
    "item_target_partition",
]
