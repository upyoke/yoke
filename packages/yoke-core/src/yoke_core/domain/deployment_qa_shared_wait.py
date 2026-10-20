"""Shared cursor waits use the deployment's existing member stage line."""

from typing import Any, Mapping
import json

from yoke_core.domain.deployment_qa_presentation_facts import run_presentation
from yoke_core.domain.deployment_qa_presentation_reads import presentation_operation


@presentation_operation
@run_presentation
def shared_plan_names(
    conn: Any, *, run_id: str, stage: str, member: int
) -> tuple[str, ...]:
    """Name only the shared groups this member's frozen stage actually owes.

    Read as one set per fact across the run's members, since resolving this
    member's groups asks every sibling what it attaches.
    """
    targets = conn.execute(
        "SELECT execution_target_json FROM qa_requirements WHERE deployment_run_id=%s "
        "AND deployment_stage=%s AND deployment_member_item_id IS NULL AND plan_id IS NOT NULL",
        (run_id, stage),
    ).fetchall()
    if not any(
        (json.loads(row[0] or "{}").get("deployment") or {}).get("shared_plan")
        for row in targets
    ):
        return ()
    from yoke_core.domain.deployment_qa_stage_contract import (
        deployment_qa_stage_subject,
    )
    from yoke_core.domain.deployment_qa_execution_target import (
        deployment_qa_execution_target,
    )
    from yoke_core.domain.deployment_qa_shared_plans import member_plan_subjects

    subject = deployment_qa_stage_subject(
        conn,
        run_id=run_id,
        stage_name=stage,
        member_item_id=member,
        require_active=False,
    )
    return tuple(
        str(group["shared_snapshot"]["plan"]["slug"])
        for group in member_plan_subjects(
            conn, subject, deployment_qa_execution_target(conn, subject)
        )
    )


def shared_execution_wait(
    execution: Mapping[str, Any], *, member: int, desired_target_digest: str
) -> dict[str, Any]:
    """Keep custody with the owner and leave the member on its durable stage wait."""
    same_target = execution["execution_target_digest"] == desired_target_digest
    execution_id, owner = str(execution["id"]), str(execution["session_id"])
    return {
        "state": "waiting",
        "deployment_run_id": execution["deployment_run_id"],
        "deployment_stage": execution["deployment_stage"],
        "deployment_member_item_id": member,
        "shared_execution_wait": {
            "execution_id": execution_id,
            "owner_session_id": owner,
            "same_target": same_target,
        },
        "reason": "shared_plan_execution_waiting",
        "recovery": (
            f"Shared QA execution {execution_id} is owned by session {owner}. "
            + (
                "Its passing evidence credits this member automatically. "
                if same_target
                else "This member is queued on the deployment stage's member line. "
            )
            + "Keep the work claim and park with yoke sessions touch --mode parked "
            f"--reason 'waiting for shared QA execution {execution_id}'; "
            "settlement wakes members still owing QA to retry their own stage/member command."
        ),
    }


def wake_shared_stage_waiters(conn: Any, execution: Mapping[str, Any]) -> None:
    """Recheck every owed group after a shared cursor releases the stage.

    Membership is the durable subscription, including members blocked by a
    different group. Host reservations would strand a member whose evidence
    was credited by the shared walk, and miss shared cases needing no host.
    """
    target = execution.get("execution_target") or {}
    if not (target.get("deployment") or {}).get("shared_plan"):
        return
    run_id, stage = execution["deployment_run_id"], execution["deployment_stage"]
    row = conn.execute(
        "SELECT project_id,status,current_stage,release_lineage FROM deployment_runs WHERE id=%s",
        (run_id,),
    ).fetchone()
    if row is None or row["status"] != "executing" or row["current_stage"] != stage:
        return
    from yoke_core.domain.deployment_qa_stage_outstanding import qa_stage_outstanding
    from yoke_core.domain.deployment_qa_stage_wake import notify_item_scoped_qa_wait

    outstanding = qa_stage_outstanding(conn, run_id=run_id, stage_name=stage)
    if outstanding is None:
        raise ValueError(
            "shared_qa_wake_unavailable: shared execution settled but stage waits "
            f"could not be read; inspect yoke deployment-runs get {run_id} and "
            "re-drive its QA stage through the control-plane operator"
        )
    from yoke_core.domain.deployment_qa_stage_acceptance import (
        STAGE_CASES_UNRESOLVED,
        STAGE_NOT_RUN,
    )

    for member, (state, lines) in outstanding.member_blockers().items():
        if member is not None:
            # The wake names what this member's stage still waits on; only a
            # stage still owed cases is handed the run recipe.
            delivery = notify_item_scoped_qa_wait(
                conn,
                run_id=run_id,
                stage_name=stage,
                item_id=member,
                project_id=int(row["project_id"]),
                reasons=(
                    f"shared execution {execution['id']} settled "
                    f"{execution['state']}; " + "; ".join(lines)
                ),
                owes_run=state in {STAGE_NOT_RUN, STAGE_CASES_UNRESOLVED},
                names_cases=True,
                revision=str(row["release_lineage"] or ""),
                target_digest=f"shared-settled:{execution['id']}:{execution['state']}",
            )
            if not delivery:
                from yoke_core.domain.project_identity import render_item_ref

                print(
                    f"shared_qa_waiter_unaddressed: {render_item_ref(conn, member)} "
                    f"still owes {run_id} stage {stage}; no holder or steering seat "
                    "can receive its wake. Staff the member, then run its stage/member QA command."
                )
    conn.commit()
