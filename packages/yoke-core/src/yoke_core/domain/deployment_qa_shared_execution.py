"""Route a member's ordered walk through its shared plan subjects."""

from functools import wraps

from yoke_core.domain.qa_obligation_settlement import (
    settled_obligation_sql,
    unanswered_attempt_sql,
)


def route_shared_plan_execution(begin):
    """Reuse completed group evidence and execute only this member's owed groups."""

    @wraps(begin)
    def routed(conn, **kwargs):
        member = kwargs.get("deployment_member_item_id")
        if member is None or kwargs.get("_deployment_subject") is not None:
            return begin(conn, **kwargs)
        from yoke_core.domain.qa_plan_execution_authority import lock_member_admission
        from yoke_core.domain.deployment_qa_stage_contract import (
            deployment_qa_stage_subject,
        )
        from yoke_core.domain.deployment_qa_execution_target import (
            deployment_qa_execution_target,
        )
        from yoke_core.domain.deployment_qa_shared_plans import member_plan_subjects
        from yoke_core.domain.deployment_qa_stage_acceptance import (
            stage_acceptance,
            completed_execution,
        )
        from yoke_core.domain.qa_execution_environment_target import target_digest

        run_id, stage = kwargs.get("deployment_run_id"), kwargs.get("deployment_stage")
        if not stage:
            return begin(conn, **kwargs)
        lock_member_admission(conn, run_id, member)
        subject = deployment_qa_stage_subject(
            conn, run_id=run_id, stage_name=stage, member_item_id=member
        )
        target = deployment_qa_execution_target(conn, subject)
        groups = member_plan_subjects(conn, subject, target)
        if not groups:
            return begin(conn, **kwargs)
        pending, completed = [], None
        for group in groups:
            group_target = deployment_qa_execution_target(conn, group)
            acceptance = stage_acceptance(
                conn,
                subject=group,
                target=group_target,
                acceptance_qa_kind="deployment_stage_acceptance",
            )
            recorded = completed_execution(
                conn,
                run_id=run_id,
                stage_name=stage,
                member_item_id=None,
                execution_target_digest=target_digest(group_target),
            )
            from yoke_core.domain.deployment_qa_stage_case_failures import case_failures

            if recorded is not None and not case_failures(
                conn,
                run_id=run_id,
                stage_name=stage,
                member_item_id=None,
                execution_target_digest=target_digest(group_target),
                shared_plan_id=group["shared_plan"]["plan_id"],
            ):
                completed = recorded
            elif not acceptance.accepted:
                pending.append(group)
        private = conn.execute(
            "SELECT COUNT(*) FROM qa_requirements WHERE deployment_run_id=%s AND deployment_stage=%s "
            "AND deployment_member_item_id=%s AND method_id IS NOT NULL "
            f"AND NOT {settled_obligation_sql(conn)} AND {unanswered_attempt_sql(conn)}",
            (run_id, stage, member),
        ).fetchone()[0]
        if private:
            private_accepted = stage_acceptance(
                conn,
                subject={**subject, "shared_plans_resolved": True},
                target=target,
                acceptance_qa_kind="deployment_stage_acceptance",
            ).accepted
            if not private_accepted:
                # Private evidence has its own cursor and custody. Completing it
                # must not start a shared campaign as a client-side continuation.
                return begin(conn, **kwargs)
        if pending:
            from yoke_core.domain.qa_plan_execution_store import (
                live_plan_execution_id,
                select_plan_execution,
                QaPlanExecutionStateError,
            )

            desired = target_digest(deployment_qa_execution_target(conn, pending[0]))
            live_id = live_plan_execution_id(
                conn,
                deployment_run_id=run_id,
                deployment_stage=stage,
            )
            if live_id:
                live = select_plan_execution(conn, live_id, lock=False)
                if live["execution_target_digest"] != desired:
                    raise QaPlanExecutionStateError(
                        f"shared_plan_execution_busy: execution {live_id} is running a different "
                        "plan group at this stage; continue that execution through its owner, then retry "
                        "this member. If its owner is gone, inspect and abort that execution before retrying."
                    )

            result = begin(
                conn,
                **{
                    **kwargs,
                    "deployment_member_item_id": None,
                    "_deployment_subject": pending[0],
                },
            )
            own_remaining = result.get("remaining_requirement_count") or 0
            return {
                **result,
                "remaining_requirement_count": own_remaining
                + sum(
                    conn.execute(
                        "SELECT COUNT(*) FROM qa_requirements WHERE deployment_run_id=%s AND deployment_stage=%s "
                        "AND deployment_member_item_id IS NULL AND execution_target_digest=%s AND method_id IS NOT NULL "
                        f"AND waived_at IS NULL AND {unanswered_attempt_sql(conn)}",
                        (
                            run_id,
                            stage,
                            target_digest(deployment_qa_execution_target(conn, group)),
                        ),
                    ).fetchone()[0]
                    for group in pending[1:]
                ),
            }
        if completed is not None:
            return {**completed, "remaining_requirement_count": 0}
        from yoke_core.domain.qa_plan_empty_roster import QaPlanRosterDischarged

        raise QaPlanRosterDischarged(
            "All attached shared plan cases were discharged; no execution remains.",
            requirement_id=0,
            qa_kind="shared_plan_discharge",
        )

    return routed
