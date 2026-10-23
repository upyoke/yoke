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
    """Wake members who can act after this shared execution settles.

    A member still waiting on a different live shared execution stays parked.
    A member whose only open case is manual keeps the manual-evidence notice
    and is not told to run now. Anyone else the stage still blocks, including
    a member owed a group nobody is executing, is woken.
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
        print(
            "shared_qa_wake_unavailable: shared execution settled but stage waits "
            f"could not be read; inspect yoke deployment-runs get {run_id} and "
            "re-drive its QA stage through the control-plane operator"
        )
        return
    from yoke_contracts.qa_case_wake_path import MANUAL
    from yoke_core.domain.deployment_qa_execution_target import (
        deployment_qa_execution_target,
    )
    from yoke_core.domain.deployment_qa_manual_wake import manual_wake_requirements
    from yoke_core.domain.deployment_qa_shared_plans import member_plan_subjects
    from yoke_core.domain.deployment_qa_stage_acceptance import (
        STAGE_CASES_UNRESOLVED,
        STAGE_NOT_RUN,
        stage_acceptance,
    )
    from yoke_core.domain.deployment_qa_stage_contract import (
        deployment_qa_stage_subject,
    )
    from yoke_core.domain.deployment_qa_stage_gate import ACCEPTANCE_QA_KIND
    from yoke_core.domain.function_target_row_project import slug_for_project_id
    from yoke_core.domain.qa_execution_environment_target import target_digest
    from yoke_core.domain.qa_plan_execution_schema import LIVE_PLAN_EXECUTION_SQL

    project_id = int(row["project_id"])
    project_slug = slug_for_project_id(conn, project_id)
    settled_id = str(execution["id"])
    live = conn.execute(
        "SELECT id, execution_target_digest, requesting_member_item_id "
        "FROM qa_plan_executions WHERE deployment_run_id=%s AND deployment_stage=%s "
        f"AND state IN ({LIVE_PLAN_EXECUTION_SQL})",
        (run_id, stage),
    ).fetchall()
    live_by_digest = {
        str(item["execution_target_digest"]): str(item["id"]) for item in live
    }
    own_digest = {
        int(item["requesting_member_item_id"]): str(item["execution_target_digest"])
        for item in live
        if item["requesting_member_item_id"] is not None
    }

    for member, (state, lines) in outstanding.member_blockers().items():
        if member is not None:
            subject = deployment_qa_stage_subject(
                conn,
                run_id=run_id,
                stage_name=stage,
                member_item_id=member,
                require_active=False,
            )
            groups = member_plan_subjects(
                conn, subject, deployment_qa_execution_target(conn, subject)
            )
            owned = own_digest.get(int(member))
            if owned is not None:
                groups = sorted(
                    groups,
                    key=lambda group: target_digest(
                        deployment_qa_execution_target(conn, group)
                    )
                    != owned,
                )
            # The first group this member would actually enter decides the
            # wake. A different live execution there means begin would only
            # park again; an owed group with no other holder can be retried.
            waiting_on_other = False
            actionable = False
            for group in groups:
                group_target = deployment_qa_execution_target(conn, group)
                if stage_acceptance(
                    conn,
                    subject=group,
                    target=group_target,
                    acceptance_qa_kind=ACCEPTANCE_QA_KIND,
                ).accepted:
                    continue
                holder = live_by_digest.get(target_digest(group_target))
                if holder is not None and holder != settled_id:
                    waiting_on_other = True
                else:
                    actionable = True
                break
            if waiting_on_other:
                continue
            owes_run = state in {STAGE_NOT_RUN, STAGE_CASES_UNRESOLVED}
            if owes_run and not actionable:
                manual = manual_wake_requirements(
                    conn,
                    run_id=run_id,
                    stage_name=stage,
                    item_ids=(int(member),),
                    project_slug=project_slug,
                )
                if manual:
                    others = conn.execute(
                        "SELECT COUNT(*) FROM qa_requirements q "
                        "WHERE q.deployment_run_id=%s AND q.deployment_stage=%s "
                        "AND q.deployment_member_item_id=%s AND q.method_id IS NOT NULL "
                        "AND q.waived_at IS NULL AND q.superseded_at IS NULL "
                        "AND q.retracted_at IS NULL "
                        "AND NOT EXISTS (SELECT 1 FROM qa_runs r "
                        "WHERE r.qa_requirement_id=q.id) "
                        "AND COALESCE(q.wake_path,'automatic')<>%s",
                        (run_id, stage, int(member), MANUAL),
                    ).fetchone()[0]
                    if int(others) == 0:
                        continue
            # The wake names what this member's stage still waits on; only a
            # stage still owed cases is handed the run recipe.
            delivery = notify_item_scoped_qa_wait(
                conn,
                run_id=run_id,
                stage_name=stage,
                item_id=member,
                project_id=project_id,
                reasons=(
                    f"shared execution {execution['id']} settled "
                    f"{execution['state']}; " + "; ".join(lines)
                ),
                owes_run=owes_run,
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
