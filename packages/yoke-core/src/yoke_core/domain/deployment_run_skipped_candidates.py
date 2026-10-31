"""Carried items a run's composition left out, and why, in one notice.

A run's candidate carries more landed code than the run delivers. Four
reasons keep a carried item out of its membership, and "why is my item not a
member" is otherwise answerable only by reading several runs and item
histories by hand:

* **held** -- another live or succeeded release already holds that landing,
  so delivering it is that run's job (:mod:`deployment_run_unheld_candidates`).
  Supplemental custody holds only on the same environment when the holder
  covers the selection and commit or no proof remains owed there;
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
from typing import Any, NamedTuple

from yoke_core.domain.deployment_run_carried_membership import (
    carried_enrollment_blocked,
    project_carried_sets,
)
from yoke_core.domain.deployment_run_composition_freeze import (
    RELEASE_MEMBERSHIP_POLICIES,
    items_requiring_release_membership,
    member_ids,
)
from yoke_core.domain.deployment_run_dependency_readiness import (
    blocker_holding_run,
    unshipped_dependency_pairs,
)
from yoke_core.domain.deployment_run_membership_removals import (
    membership_removals,
)
from yoke_core.domain.dependency_types import GateResult
from yoke_core.domain.deployment_run_unheld_candidates import (
    CustodyResolution,
    HeldCandidate,
    resolve_candidate_custody,
)
from yoke_core.domain.item_ref_render import render_item_ref_lookup
from yoke_core.domain.workflow_item_binding_validation import read_pinned_items
from yoke_core.domain.workflow_delivery_binding_validation import (
    delivery_ready_for_stage,
)
from yoke_core.domain.workflow_runtime import (
    ENGINE_TERMINAL_STAGE_IDS,
)


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
    for item_id, item in read_pinned_items(conn, carried).items():
        runtime, status = item.require_runtime(conn, item_id), item.status
        if (
            status not in runtime.terminal_stage_ids
            and status not in ENGINE_TERMINAL_STAGE_IDS
            and str(runtime.policies.get("delivery")) in RELEASE_MEMBERSHIP_POLICIES
            and not delivery_ready_for_stage(runtime, status)
        ):
            found.append((item_id, status))
    return tuple(found)


def _describe_blocked(
    conn: Any, ref: Any, dependent: int, blocker: int, reason: str
) -> str:
    """One skipped dependent, naming the release still holding its blocker."""
    line = f"{ref(dependent)} blocked by {ref(blocker)} ({reason}"
    if holding := blocker_holding_run(conn, blocker):
        run_id, state = holding
        line += (
            f"; held by {run_id} ({state}) -- the first release after "
            f"{run_id} settles enrolls it"
        )
    return line + ")"


def _held_descriptions(
    conn: Any, run_id: str, held: tuple[HeldCandidate, ...]
) -> list[str]:
    """Name the recorded holder without inventing commit restrictions."""
    return [f"{r.item_ref} held by {r.run_id} ({r.run_status})" for r in held]


class SkippedCandidates(NamedTuple):
    """What a run's composition left out, resolved once for every reader."""

    held: tuple[HeldCandidate, ...]
    removed: tuple[Mapping[str, Any], ...]
    rework: tuple[tuple[int, str], ...]
    blocked: list[tuple[int, int, GateResult]]


def skipped_candidates(
    conn: Any,
    run_id: str,
    *,
    custody: CustodyResolution | None = None,
    carried_work: Mapping[str, Any] | None = None,
) -> SkippedCandidates | None:
    """Every carried item this run leaves out, or ``None`` when it may not enroll.

    Pass *custody* and *carried_work* to reuse what composition already
    resolved; without *carried_work* the in-rework part is not reported,
    since deriving it again here would repeat a source walk.
    """
    if carried_enrollment_blocked(conn, run_id):
        return None
    resolved = custody or resolve_candidate_custody(conn, run_id)
    held = resolved.held
    removed = tuple(membership_removals(conn, run_id))
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
    members = set(member_ids(conn, run_id))
    candidates = sorted((range_ids | set(resolved.enrollable)) - excluded - members)
    required = items_requiring_release_membership(conn, candidates)
    blocked = unshipped_dependency_pairs(
        conn,
        [item_id for item_id in candidates if item_id in required],
        member_ids=members,
    )
    return SkippedCandidates(held, removed, rework, blocked)


def describe_skipped(conn: Any, run_id: str, skipped: SkippedCandidates | None) -> str:
    """The one notice naming every skipped carried item and why."""
    if skipped is None:
        return ""
    held, removed, rework, blocked = skipped
    ref = render_item_ref_lookup(
        conn,
        [i for i, _ in rework]
        + [int(entry["item_id"]) for entry in removed]
        + [i for dependent, blocker, _ in blocked for i in (dependent, blocker)],
    )
    parts: list[str] = []
    if blocked:
        parts.append(
            "open dependencies on unshipped items; the first release after the blocker ships enrolls them: "
            + "; ".join(
                _describe_blocked(conn, ref, dependent, blocker, str(verdict.reason))
                for dependent, blocker, verdict in blocked
            )
        )
    if held:
        parts.append(
            "held by a release that owes their delivery: "
            + "; ".join(_held_descriptions(conn, run_id, held))
        )
    if rework:
        parts.append(
            "WARNING: merged into this candidate but not at release yet — "
            "wait for it or add-item once it reaches release: "
            + "; ".join(
                f"{ref(item_id)} (status={status})" for item_id, status in rework
            )
        )
    if removed:
        parts.append(
            "removed from this run: "
            + "; ".join(
                f"{ref(int(entry['item_id']))} "
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


def skipped_candidate_notice(
    conn: Any,
    run_id: str,
    *,
    custody: CustodyResolution | None = None,
    carried_work: Mapping[str, Any] | None = None,
) -> str:
    """Name every carried item this run left out, including unshipped blockers."""
    return describe_skipped(
        conn,
        run_id,
        skipped_candidates(conn, run_id, custody=custody, carried_work=carried_work),
    )


__all__ = [
    "SkippedCandidates",
    "carried_items_in_rework",
    "describe_skipped",
    "skipped_candidate_notice",
    "skipped_candidates",
]
