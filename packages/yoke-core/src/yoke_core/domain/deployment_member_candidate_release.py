"""Release failed member QA only when its recorded correction cannot ship here."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.db_helpers import query_one
from yoke_core.domain.project_identity import render_item_ref

#: Removal source for a failed member whose recorded correction already
#: landed outside this run's frozen lineage: its rework is done, so the
#: owner waits on the later release instead of classifying the failure.
CORRECTION_RELEASE_REMOVED_BY = "item QA failure"


def candidate_exclusions(
    conn: Any,
    run_id: str,
    members: list[dict[str, Any]],
    *,
    include_lane_head: bool,
    unproven: dict[int, str] | None = None,
) -> list[tuple[int, str, str]]:
    """Resolve containment before locks; return identities to re-check under them.

    Pass *unproven* to collect, per item, why containment could not be
    decided; those members are neither excluded nor proven contained.
    """
    from yoke_core.domain.dash_lane_head_staleness import active_lane_head
    from yoke_core.domain.delivery_evidence_ladder import item_merge_identity
    from yoke_core.domain.deployment_run_candidate_containment import (
        NOT_CONTAINED,
        UNDETERMINED,
        CandidateContainment,
    )
    from yoke_core.domain.deployment_run_project_sources import recorded_source_sha
    from yoke_core.domain.relayed_containment_attestation import take_relayed_verdict

    run = query_one(
        conn,
        "SELECT project_id,release_lineage,bound_sources FROM deployment_runs WHERE id=%s",
        (run_id,),
    )
    if run is None:
        return []
    excluded: list[tuple[int, str, str]] = []
    walkers: dict[int, CandidateContainment] = {}
    for member in members:
        item_id = int(member["item_id"])
        project = query_one(
            conn, "SELECT project_id FROM items WHERE id=%s", (item_id,)
        )
        if project is None:
            continue
        project_id = int(project["project_id"])
        lineage = recorded_source_sha(run, project_id)
        merge = item_merge_identity(conn, item_id)
        head = active_lane_head(conn, item_id) if include_lane_head else ""
        if not merge:
            continue
        if not lineage:
            why = "has no pinned project source; bind its project source before retrying QA release"
            print(
                f"member_candidate_containment_unproven: {render_item_ref(conn, item_id)} on {run_id} {why}."
            )
            if unproven is not None:
                unproven[item_id] = why
            continue
        if project_id not in walkers:
            walkers[project_id] = CandidateContainment(
                conn, project_id, candidate_lineage=lineage
            )
        for sha in dict.fromkeys(s for s in (merge, head) if s):
            verdict = walkers[project_id].contains(sha)
            if verdict.state == UNDETERMINED:
                verdict = take_relayed_verdict(
                    verdict,
                    conn,
                    item_id=item_id,
                    run_id=run_id,
                    candidate=lineage,
                    commit_sha=sha,
                )
            if verdict.state == UNDETERMINED:
                why = f"{verdict.reason}. {verdict.recovery}"
                print(
                    f"member_candidate_containment_unproven: {render_item_ref(conn, item_id)} on {run_id}: {why}"
                )
                if unproven is not None:
                    unproven[item_id] = why
            if verdict.state == NOT_CONTAINED:
                excluded.append((item_id, merge, head))
                break
    return excluded


def release_failed_member(conn: Any, *, run_id: str, stage: str, item_id: int) -> bool:
    """Use the independent item-QA removal guards and retain unknown candidates."""
    from yoke_core.domain.delivery_evidence_ladder import item_merge_identity
    from yoke_core.domain.deployment_run_member_removal import remove_member_on
    from yoke_core.domain.deployment_run_member_removal_read import read_removal
    from yoke_core.domain.deployment_runs_lock import lock_run_with_stable_membership

    excluded = candidate_exclusions(
        conn, run_id, [{"item_id": item_id}], include_lane_head=False
    )
    if not excluded:
        return False
    _, merge, _ = excluded[0]
    read = read_removal(conn, run_id=run_id, item_ids=(item_id,))
    run_status, held = lock_run_with_stable_membership(conn, run_id)
    current = query_one(
        conn, "SELECT current_stage FROM deployment_runs WHERE id=%s", (run_id,)
    )
    if (
        run_status not in {"executing", "failed"}
        or current["current_stage"] not in {stage, f"{stage}-failed"}
        or item_id not in held
        or item_merge_identity(conn, item_id) != merge
    ):
        conn.commit()
        return False
    if not read.projection.holds(conn):
        read = read_removal(conn, run_id=run_id, item_ids=(item_id,))
    if read.refusal is not None:
        conn.commit()
        print(
            f"member_candidate_release_held: {render_item_ref(conn, item_id)} on {run_id}: {read.refusal}"
        )
        return False
    reason = "failed item QA cannot pass against this run's frozen lineage; recorded merge is not contained; awaiting a later release"
    ref = remove_member_on(
        conn,
        run_id,
        item_id,
        reason=reason,
        removed_by=CORRECTION_RELEASE_REMOVED_BY,
    )
    conn.commit()
    print(f"Released {ref} from run {run_id}: {reason}.")
    return True


def release_replaced_members(
    conn: Any,
    run_id: str,
    members: list[dict[str, Any]],
    *,
    unproven: dict[int, str] | None = None,
) -> list[str]:
    """Release only definite exclusions from the frozen candidate; name each.

    Settlement passes members at their release wait; settlement and resume
    both pass members marked ``reopened`` that left delivery readiness after
    the run froze. Either is released when its recorded merge or active lane
    head is outside the run's frozen lineage, bypassing the settled-QA guard
    because the candidate this run carries is no longer the item's. Resolve
    repository comparisons and the run's shared groups before taking the run
    row; re-check identities under the workflow-binding locks so a concurrent
    landing cannot be removed on an answer about a different commit. Unknown
    containment remains a blocker and is collected in *unproven*.
    """
    from yoke_core.domain.dash_lane_head_staleness import active_lane_head
    from yoke_core.domain.delivery_evidence_ladder import item_merge_identity
    from yoke_core.domain.deployment_run_member_removal import (
        REOPENED_REASON,
        REOPENED_REMOVED_BY,
        REPLACED_REASON,
        SETTLEMENT_REMOVED_BY,
        remove_members_on,
    )
    from yoke_core.domain.deployment_run_member_removal_read import read_removal
    from yoke_core.domain.deployment_runs_lock import lock_run_with_stable_membership

    excluded = candidate_exclusions(
        conn, run_id, members, include_lane_head=True, unproven=unproven
    )
    if not excluded:
        return []
    reopened = {int(m["item_id"]) for m in members if m.get("reopened")}
    read = read_removal(conn, run_id=run_id, guard=False)
    status, held = lock_run_with_stable_membership(conn, run_id)
    if status not in {"created", "executing", "failed"}:
        conn.commit()
        return []
    if not read.projection.holds(conn):
        read = read_removal(conn, run_id=run_id, guard=False)
    current = [
        item_id
        for item_id, merge, head in excluded
        if item_id in held
        and item_merge_identity(conn, item_id) == merge
        and active_lane_head(conn, item_id) == head
    ]
    released: list[str] = []
    for removed_by, reason, ids in (
        (REOPENED_REMOVED_BY, REOPENED_REASON, [i for i in current if i in reopened]),
        (
            SETTLEMENT_REMOVED_BY,
            REPLACED_REASON,
            [i for i in current if i not in reopened],
        ),
    ):
        for ref in remove_members_on(
            conn,
            run_id,
            ids,
            reason=reason,
            removed_by=removed_by,
        ).values():
            print(f"Released {ref} from run {run_id}: {reason}.")
            released.append(ref)
    conn.commit()
    return released
