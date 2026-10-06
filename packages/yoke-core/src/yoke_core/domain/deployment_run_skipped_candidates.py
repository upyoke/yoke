"""Carried items a run's composition left out, and why, in one notice.

A run's candidate carries more landed code than the run delivers. Four
reasons keep a carried item out of its membership, and "why is my item not a
member" is otherwise answerable only by reading several runs and item
histories by hand:

* **held** -- another live or succeeded release already holds that landing,
  so delivering it is that run's job (:mod:`deployment_run_unheld_candidates`);
* **in rework** -- the item landed, then went back before its workflow's
  release stage (failed QA sent it to ``implementing``, say). Its code still
  ships, but it is not ready to be delivered, so enrollment skips it and a
  later release enrolls it once it returns;
* **removed** -- an operator took it out of this run with a recorded reason
  (:mod:`deployment_run_membership_removals`).
* **blocked** -- an open dependency needs a blocker that has not shipped yet.
  A blocker a live or settling release still holds has not shipped either:
  the dependency gate counts only a recorded ``succeeded`` run, so the
  notice names that run, and the first release after it settles enrolls
  the dependent.

Composition reports them together whenever it reports itself, so an
operator reads one notice rather than reconciling three. It is silent when the
run may not enroll at all, because then nothing was skipped.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from yoke_core.domain.deployment_run_carried_membership import (
    carried_enrollment_blocked,
    project_carried_sets,
)
from yoke_core.domain.deployment_run_composition_freeze import (
    RELEASE_MEMBERSHIP_POLICIES,
    item_requires_release_membership,
    member_ids,
)
from yoke_core.domain.deployment_run_dependency_readiness import (
    blocker_holding_run,
    unshipped_dependency_pairs,
)
from yoke_core.domain.deployment_run_membership_removals import (
    membership_removals,
)
from yoke_core.domain.deployment_run_unheld_candidates import (
    CustodyResolution,
    resolve_candidate_custody,
)
from yoke_core.domain.project_identity import render_item_ref
from yoke_core.domain.workflow_delivery_binding_validation import (
    delivery_ready_for_stage,
)
from yoke_core.domain.workflow_runtime import (
    ENGINE_TERMINAL_STAGE_IDS,
    load_item_workflow_runtime,
)


def _rework_status(conn: Any, item_id: int) -> str:
    """The status of a carried item back before its release stage, else ``''``."""
    row = conn.execute(
        "SELECT status FROM items WHERE id=%s", (int(item_id),)
    ).fetchone()
    if row is None:
        return ""
    status = str(row["status"] if hasattr(row, "keys") else row[0])
    runtime = load_item_workflow_runtime(conn, int(item_id))
    if status in runtime.terminal_stage_ids or status in ENGINE_TERMINAL_STAGE_IDS:
        return ""
    if str(runtime.policies.get("delivery")) not in RELEASE_MEMBERSHIP_POLICIES:
        return ""
    return "" if delivery_ready_for_stage(runtime, status) else status


def carried_items_in_rework(
    conn: Any,
    run_id: str,
    carried_work: Mapping[str, Any],
    *,
    exclude: frozenset[int] = frozenset(),
) -> tuple[tuple[int, str], ...]:
    """Carried items not yet back at their release stage, with their status."""
    members = set(member_ids(conn, run_id))
    carried = sorted(
        {
            int(entry["item_id"])
            for project_set in project_carried_sets(carried_work)
            if bool((project_set.get("derivation") or {}).get("contents_known"))
            for entry in project_set.get("items") or []
        }
        - members
        - exclude
    )
    found: list[tuple[int, str]] = []
    for item_id in carried:
        if status := _rework_status(conn, item_id):
            found.append((item_id, status))
    return tuple(found)


def _describe_blocked(conn: Any, dependent: int, blocker: int, reason: str) -> str:
    """One skipped dependent, naming the release still holding its blocker."""
    line = (
        f"{render_item_ref(conn, dependent)} blocked by "
        f"{render_item_ref(conn, blocker)} ({reason}"
    )
    if holding := blocker_holding_run(conn, blocker):
        run_id, state = holding
        line += (
            f"; held by {run_id} ({state}) -- the first release after "
            f"{run_id} settles enrolls it"
        )
    return line + ")"


def skipped_candidate_notice(
    conn: Any,
    run_id: str,
    *,
    custody: CustodyResolution | None = None,
    carried_work: Mapping[str, Any] | None = None,
) -> str:
    """Name every carried item this run left out, including unshipped blockers.

    Pass *custody* and *carried_work* to reuse what composition already
    resolved; without *carried_work* the in-rework part is not reported,
    since deriving it again here would repeat a source walk.
    """
    if carried_enrollment_blocked(conn, run_id):
        return ""
    resolved = custody or resolve_candidate_custody(conn, run_id)
    held = resolved.held
    removed = membership_removals(conn, run_id)
    excluded = frozenset(record.item_id for record in held) | frozenset(
        int(entry["item_id"]) for entry in removed
    )
    rework = (
        carried_items_in_rework(conn, run_id, carried_work, exclude=excluded)
        if carried_work is not None
        else ()
    )
    range_ids = {
        int(entry["item_id"])
        for project_set in project_carried_sets(carried_work or {})
        if bool((project_set.get("derivation") or {}).get("contents_known"))
        for entry in project_set.get("items") or []
    }
    candidates = sorted(
        (range_ids | set(resolved.enrollable))
        - excluded
        - set(member_ids(conn, run_id))
    )
    blocked = unshipped_dependency_pairs(
        conn,
        [
            item_id
            for item_id in candidates
            if item_requires_release_membership(conn, item_id)
        ],
    )
    parts: list[str] = []
    if blocked:
        parts.append(
            "open dependencies on unshipped items; the first release after the blocker ships enrolls them: "
            + "; ".join(
                _describe_blocked(conn, dependent, blocker, str(verdict.reason))
                for dependent, blocker, verdict in blocked
            )
        )
    if held:
        parts.append(
            "held by a release that owes their delivery: "
            + "; ".join(
                f"{record.item_ref} held by {record.run_id} ({record.run_status})"
                for record in held
            )
        )
    if rework:
        parts.append(
            "WARNING: merged into this candidate but not at release yet — "
            "wait for it or add-item once it reaches release: "
            + "; ".join(
                f"{render_item_ref(conn, item_id)} (status={status})"
                for item_id, status in rework
            )
        )
    if removed:
        parts.append(
            "removed from this run: "
            + "; ".join(
                f"{render_item_ref(conn, int(entry['item_id']))} "
                f"({entry.get('reason') or 'no reason recorded'})"
                for entry in removed
            )
        )
    if not parts:
        return ""
    count = len(held) + len(rework) + len(removed) + len({d for d, _, _ in blocked})
    return (
        f"Skipped {count} carried item(s) this run does not deliver -- "
        + " | ".join(parts)
    )


__all__ = ["carried_items_in_rework", "skipped_candidate_notice"]
