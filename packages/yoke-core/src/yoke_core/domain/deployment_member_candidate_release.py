"""Release failed member QA only when its recorded correction cannot ship here."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.db_helpers import query_one
from yoke_core.domain.project_identity import render_item_ref


def candidate_exclusions(
    conn: Any, run_id: str, members: list[dict[str, Any]], *, include_lane_head: bool
) -> list[tuple[int, str, str]]:
    """Resolve containment before locks; return identities to re-check under them."""
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
            print(
                f"member_candidate_containment_unproven: {render_item_ref(conn, item_id)} on {run_id} has no pinned project source; bind its project source before retrying QA release."
            )
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
                print(
                    f"member_candidate_containment_unproven: {render_item_ref(conn, item_id)} on {run_id}: {verdict.reason}. {verdict.recovery}"
                )
            if verdict.state == NOT_CONTAINED:
                excluded.append((item_id, merge, head))
                break
    return excluded


def release_failed_member(conn: Any, *, run_id: str, stage: str, item_id: int) -> bool:
    """Use the independent item-QA removal guards and retain unknown candidates."""
    from yoke_core.domain.delivery_evidence_ladder import item_merge_identity
    from yoke_core.domain.deployment_run_member_removal import (
        _require_removable,
        remove_member_on,
    )
    from yoke_core.domain.deployment_runs_lock import lock_run_with_stable_membership

    excluded = candidate_exclusions(
        conn, run_id, [{"item_id": item_id}], include_lane_head=False
    )
    if not excluded:
        return False
    _, merge, _ = excluded[0]
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
    try:
        _require_removable(conn, run_id, item_id)
    except ValueError as exc:
        conn.commit()
        print(
            f"member_candidate_release_held: {render_item_ref(conn, item_id)} on {run_id}: {exc}"
        )
        return False
    reason = "failed item QA cannot pass against this run's frozen lineage; recorded merge is not contained; awaiting a later release"
    ref = remove_member_on(
        conn, run_id, item_id, reason=reason, removed_by="item QA failure"
    )
    conn.commit()
    print(f"Released {ref} from run {run_id}: {reason}.")
    return True
