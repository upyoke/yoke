"""Release a run's member to a later candidate without erasing QA history."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.db_helpers import connect, query_one, query_rows
from yoke_core.domain.deployment_run_composition_guard import (
    frozen_mutation_refusal,
    has_frozen_composition,
)
from yoke_core.domain.deployment_run_membership_removals import (
    record_membership_removal,
)
from yoke_core.domain.deployment_runs_lock import (
    lock_run,
    lock_run_with_stable_membership,
)
from yoke_core.domain.project_identity import render_item_ref
from yoke_core.domain.qa_plan_attachment_retract import retract_requirements
from yoke_core.domain.qa_obligation_settlement import settled_obligation_sql
from yoke_core.domain.workflow_item_binding_lock import lock_item_workflow_bindings


def _require_removable(conn: Any, run_id: str, item_id: int) -> bool:
    """Keep ordinary composition mutable; narrow executing edits to owed item QA."""
    status = lock_run(conn, run_id)
    if status is None:
        raise LookupError(f"deployment run '{run_id}' not found")
    if status == "created":
        if has_frozen_composition(conn, run_id):
            raise ValueError(frozen_mutation_refusal(run_id, "membership")[7:])
        return False
    if status != "executing":
        raise ValueError(
            f"deployment run '{run_id}' is {status}; removal is allowed only while "
            "status='created' or executing at item QA. Use a later release."
        )
    from yoke_core.domain.deployment_qa_run_acceptance import (
        current_item_qa,
        pinned_stages,
    )

    row = query_one(
        conn,
        "SELECT current_stage,settling_at FROM deployment_runs WHERE id=%s",
        (run_id,),
    )
    stages = pinned_stages(conn, run_id)
    current = next((s for s in stages if s.get("name") == row["current_stage"]), {})
    if (
        row["settling_at"]
        or current.get("step_runner") != "qa"
        or current.get("scope") != "item"
    ):
        boundary = (
            "run is at a shared run-level gate; the member is part of the shared result"
            if current.get("scope") == "run"
            and current.get("step_runner") in {"qa", "human-approval"}
            else "frozen membership cannot be removed at this boundary"
        )
        raise ValueError(
            f"run {run_id} is not at an item-scoped QA stage: {boundary}. "
            "Settle the current gate or repair settlement, then deliver the member through a later release."
        )
    if any(
        s.get("step_runner") == "human-approval"
        or (s.get("step_runner") == "qa" and s.get("scope") == "run")
        for s in stages
    ):
        raise ValueError(
            f"run {run_id} has shared run-level QA or approval; the member is part "
            "of the shared result. Settle the shared gates instead of removing it."
        )
    item = query_one(conn, "SELECT status FROM items WHERE id=%s", (item_id,))
    member = query_one(
        conn,
        "SELECT 1 FROM deployment_run_items WHERE run_id=%s AND item_id=%s",
        (run_id, item_id),
    )
    if member is None:
        return True  # The shared write reports the public non-member identity.
    if item["status"] in {"done", "cancelled", "stopped"}:
        raise ValueError(
            f"member {render_item_ref(conn, item_id)} is already closed; retain its delivery evidence."
        )
    answer = current_item_qa(
        conn,
        run_id=run_id,
        item_id=item_id,
        current_stage=str(row["current_stage"]),
        stages=stages,
    )
    if answer is None or answer.accepted:
        reason = "already settled" if answer is not None else "QA cannot be evaluated"
        raise ValueError(
            f"member {render_item_ref(conn, item_id)}: {reason}; retain its evidence and inspect `yoke deployment-runs get {run_id}`."
        )
    return True


def remove_member_on(
    conn: Any,
    run_id: str,
    item_id: int,
    *,
    reason: str,
    session_id: str | None = None,
    actor_id: int | None = None,
) -> str:
    """Apply the audited removal and retire only this run's outstanding member QA.

    Caller owns the locks and transaction. Standing item plans and passing
    evidence survive; the next release materializes fresh run-bound copies.
    """
    ref = render_item_ref(conn, item_id)
    deleted = conn.execute(
        "DELETE FROM deployment_run_items WHERE run_id=%s AND item_id=%s",
        (run_id, item_id),
    )
    if not getattr(deleted, "rowcount", 0):
        raise LookupError(
            f"{ref} is not a member of deployment run '{run_id}'; read `yoke deployment-runs get {run_id}` for its members"
        )
    record_membership_removal(
        conn, run_id, item_id, reason=reason, session_id=session_id, actor_id=actor_id
    )
    rows = query_rows(
        conn,
        "SELECT r.id FROM qa_requirements r WHERE r.deployment_run_id=%s "
        "AND r.deployment_member_item_id=%s AND r.blocking_mode='blocking' "
        f"AND NOT {settled_obligation_sql(conn, 'r')} "
        "AND NOT EXISTS (SELECT 1 FROM qa_runs qr WHERE qr.qa_requirement_id=r.id AND qr.verdict='pass')",
        (run_id, item_id),
    )
    retract_requirements(
        conn, [int(r["id"]) for r in rows], reason=reason, source="operator"
    )
    from yoke_core.domain.deployment_qa_stage_wake_withdraw import (
        withdraw_deployment_qa_wait_wakes,
    )

    withdraw_deployment_qa_wait_wakes(
        conn, run_id=run_id, item_id=item_id, reason="member_removed"
    )
    return ref


def cmd_remove_item(
    run_id: str,
    item_id: int,
    *,
    reason: str,
    session_id: str | None = None,
    actor_id: int | None = None,
    db_path: str | None = None,
) -> str:
    """Remove a created member, or one still owing QA on an independent item stage."""
    reason = str(reason or "").strip()
    if not reason:
        raise ValueError(
            "a membership removal needs --reason naming why this run must not deliver the item; it is recorded on the run for audit"
        )
    conn = connect(db_path)
    try:
        lock_item_workflow_bindings(conn, (int(item_id),))
        executing = _require_removable(conn, run_id, int(item_id))
        ref = remove_member_on(
            conn,
            run_id,
            int(item_id),
            reason=reason,
            session_id=session_id,
            actor_id=actor_id,
        )
        conn.commit()
        recovery = f"Re-attach while created with `yoke deployment-runs add-item {run_id} {ref}`."
        if executing:
            from yoke_core.domain.deployment_run_auto_completion import (
                continue_after_settlement,
            )

            result = continue_after_settlement(conn, run_id)
            if not result.completed:
                from yoke_core.domain.deployment_run_driver_notice import (
                    push_run_scoped_notice,
                )

                project = query_one(
                    conn,
                    "SELECT project_id FROM deployment_runs WHERE id=%s",
                    (run_id,),
                )
                delivery = push_run_scoped_notice(
                    conn,
                    project_id=int(project["project_id"]),
                    body_for_route=lambda _route: (
                        f"Removed {ref} from run {run_id}: {reason}. "
                        "Re-evaluate its remaining item QA and continue this same run "
                        f"with `yoke watch deploy -- {run_id}` under the project deploy lock."
                    ),
                    idempotency_key=f"deployment-member-removal:{run_id}:{item_id}",
                )
                conn.commit()
                if not delivery:
                    print(
                        f"Run {run_id} removal is durable but no driver received continuation; re-drive under the project deploy lock."
                    )
            recovery = (
                result.failure
                or result.waiting
                or "The run finished with its remaining members."
            )
        return (
            f"Removed {ref} from run {run_id} ({reason}). Composition will not "
            "re-enroll it; its landed code still ships with this candidate and "
            f"a later release enrolls it. {recovery}"
        )
    finally:
        conn.close()


def release_replaced_members(
    conn: Any, run_id: str, members: list[dict[str, Any]]
) -> None:
    """At settlement, release only definite exclusions from the frozen candidate.

    Resolve repository comparisons before taking the run row; re-check identities
    under the workflow-binding locks so a concurrent landing cannot be removed on
    an answer about a different commit. Unknown containment remains a blocker.
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
    excluded: list[tuple[int, str, str]] = []
    walkers: dict[int, CandidateContainment] = {}
    for member in members:
        item_id = int(member["item_id"])
        project = query_one(
            conn, "SELECT project_id FROM items WHERE id=%s", (item_id,)
        )
        project_id = int(project["project_id"])
        lineage = recorded_source_sha(run, project_id)
        merge = item_merge_identity(conn, item_id)
        head = active_lane_head(conn, item_id)
        if not lineage or not merge:
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
            if verdict.state == NOT_CONTAINED:
                excluded.append((item_id, merge, head))
                break
    if not excluded:
        return
    status, held = lock_run_with_stable_membership(conn, run_id)
    if status != "executing":
        return
    for item_id, merge, head in excluded:
        if (
            item_id not in held
            or item_merge_identity(conn, item_id) != merge
            or active_lane_head(conn, item_id) != head
        ):
            continue
        reason = "current candidate is not contained in this run's frozen lineage; awaiting a later release"
        ref = remove_member_on(conn, run_id, item_id, reason=reason)
        print(f"Released {ref} from settling run {run_id}: {reason}.")
    conn.commit()
