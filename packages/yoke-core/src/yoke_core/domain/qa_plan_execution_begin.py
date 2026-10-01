"""Creation and resumption of durable ordered QA executions."""

from __future__ import annotations

from typing import Any

from uuid import uuid4

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.qa_plan_execution_authority import (
    lock_member_admission,
    plan_execution_is_abandoned,
)
from yoke_core.domain.qa_plan_execution_continuation import (
    resolve_continuation_source,
)
from yoke_core.domain.qa_plan_execution_lifecycle import (
    STALE_PLAN_EXECUTION_REASON,
    finish_plan_execution,
)

from yoke_core.domain.qa_plan_execution_store import (
    QaPlanExecutionStateError,
    build_execution_roster,
    canonical,
    converge_plan_execution_insert_race,
    live_plan_execution_id,
    lock_plan_execution,
    marker,
    resume_owned_plan_execution,
    roster_digest,
    same_owner,
    select_plan_execution,
)
from yoke_core.domain.qa_plan_execution_target_snapshot import (
    execution_target_for_roster,
    require_execution_target,
)
from yoke_core.domain.qa_plan_execution_roster import (
    validate_roster_machine,
)

from yoke_core.domain.workflow_item_binding_lock import (
    lock_item_workflow_bindings,
    rollback_workflow_binding_write_errors,
)


@rollback_workflow_binding_write_errors
def begin_plan_execution(
    conn: Any,
    *,
    item_id: int | None = None,
    transition_id: str | None = None,
    deployment_run_id: str | None = None,
    deployment_stage: str | None = None,
    deployment_member_item_id: int | None = None,
    machine: str | None = None,
    continue_mission: bool = False,
    actor_id: str | None,
    session_id: str,
) -> dict[str, Any]:
    """Create or resume the one live execution for a QA subject.

    ``continue_mission`` asks for the one variant that is not a plain start:
    a fresh execution over the same roster that resumes a mission walk the
    stale sweep settled while its walker was parked. It records its own runs
    and reaches no host baseline, so the machine keeps the state the settled
    walk built. :mod:`yoke_core.domain.qa_plan_execution_continuation` owns
    which prior executions qualify.
    """
    if not str(session_id or "").strip():
        raise QaPlanExecutionStateError(
            "ordered QA plan execution requires an owning session"
        )
    if (item_id is None) == (deployment_run_id is None):
        raise QaPlanExecutionStateError(
            "exactly one QA plan execution subject is required"
        )
    if item_id is not None and not str(transition_id or "").strip():
        raise QaPlanExecutionStateError(
            "item QA plan execution requires a workflow transition"
        )
    if deployment_run_id is not None and transition_id is not None:
        raise QaPlanExecutionStateError(
            "deployment-run QA plan execution has no workflow transition"
        )
    if deployment_member_item_id is not None and deployment_stage is None:
        raise QaPlanExecutionStateError("deployment member requires deployment stage")
    expected_deployment_target = None
    expected_deployment_target_digest = None
    if deployment_stage is not None:
        lock_member_admission(conn, deployment_run_id, deployment_member_item_id)
        from yoke_core.domain.deployment_qa_execution_target import (
            deployment_qa_execution_target,
        )
        from yoke_core.domain.deployment_qa_stage_contract import (
            deployment_qa_stage_subject,
        )

        subject = deployment_qa_stage_subject(
            conn,
            run_id=str(deployment_run_id),
            stage_name=deployment_stage,
            member_item_id=deployment_member_item_id,
        )
        expected_deployment_target = deployment_qa_execution_target(conn, subject)
        from yoke_core.domain.qa_execution_environment_target import target_digest

        expected_deployment_target_digest = target_digest(expected_deployment_target)
    if item_id is not None:
        lock_item_workflow_bindings(conn, (int(item_id),))
    from yoke_core.domain.qa_case_execution_context import (
        execution_host_capability_kinds,
    )

    host_capabilities = execution_host_capability_kinds(
        conn,
        session_id=session_id,
    )
    roster = build_execution_roster(
        conn,
        item_id=item_id,
        transition_id=transition_id,
        deployment_run_id=deployment_run_id,
        deployment_stage=deployment_stage,
        deployment_member_item_id=deployment_member_item_id,
        execution_target_digest=expected_deployment_target_digest,
        host_capability_kinds=host_capabilities,
    )
    from yoke_core.domain.qa_member_machine_partitions import member_machine_partition

    roster, remaining, completed = member_machine_partition(
        conn,
        roster,
        deployment_run_id=deployment_run_id,
        deployment_stage=deployment_stage,
        deployment_member_item_id=deployment_member_item_id,
        machine=machine,
    )
    if completed is not None:
        return {**completed, "remaining_requirement_count": remaining}
    validate_roster_machine(conn, roster, machine)
    digest = roster_digest(roster)
    execution_target, execution_target_digest = execution_target_for_roster(roster)
    if expected_deployment_target is not None and canonical(
        execution_target
    ) != canonical(expected_deployment_target):
        raise QaPlanExecutionStateError(
            "materialized QA roster does not match the active deployment target"
        )
    existing_id = live_plan_execution_id(
        conn,
        item_id=item_id,
        transition_id=transition_id,
        deployment_run_id=deployment_run_id,
        deployment_stage=deployment_stage,
        deployment_member_item_id=deployment_member_item_id,
    )
    continues_execution_id = (
        resolve_continuation_source(
            conn,
            live_execution_id=existing_id,
            item_id=item_id,
            transition_id=transition_id,
            deployment_run_id=deployment_run_id,
            deployment_stage=deployment_stage,
            deployment_member_item_id=deployment_member_item_id,
        )
        if continue_mission
        else None
    )
    if existing_id is not None:
        existing = lock_plan_execution(conn, existing_id)
        if existing["state"] in {
            "active",
            "waiting",
            "awaiting_agent_review",
        }:
            if same_owner(existing, actor_id=actor_id, session_id=session_id):
                require_execution_target(existing)
                return {
                    **resume_owned_plan_execution(conn, existing, digest=digest),
                    "remaining_requirement_count": remaining,
                }
            if not plan_execution_is_abandoned(conn, existing):
                conn.rollback()
                raise QaPlanExecutionStateError(
                    "another actor or session owns the active QA plan execution"
                )
            finish_plan_execution(
                conn,
                existing,
                state="aborted",
                reason=STALE_PLAN_EXECUTION_REASON,
            )

            if item_id is not None:
                lock_item_workflow_bindings(conn, (int(item_id),))
            lock_member_admission(conn, deployment_run_id, deployment_member_item_id)
            roster = build_execution_roster(
                conn,
                item_id=item_id,
                transition_id=transition_id,
                deployment_run_id=deployment_run_id,
                deployment_stage=deployment_stage,
                deployment_member_item_id=deployment_member_item_id,
                execution_target_digest=expected_deployment_target_digest,
                host_capability_kinds=host_capabilities,
            )
            roster, remaining, completed = member_machine_partition(
                conn,
                roster,
                deployment_run_id=deployment_run_id,
                deployment_stage=deployment_stage,
                deployment_member_item_id=deployment_member_item_id,
                machine=machine,
            )
            if completed is not None:
                return {**completed, "remaining_requirement_count": remaining}
            validate_roster_machine(conn, roster, machine)
            digest = roster_digest(roster)
            execution_target, execution_target_digest = execution_target_for_roster(
                roster
            )

    execution_id = str(uuid4())
    now = iso8601_now()
    placeholder = marker(conn)
    try:
        conn.execute(
            "INSERT INTO qa_plan_executions("
            "id,item_id,deployment_run_id,deployment_stage,"
            "deployment_member_item_id,transition_id,actor_id,session_id,"
            "roster_digest,"
            "roster_json,execution_target_json,execution_target_digest,"
            "continues_execution_id,"
            "cursor_ordinal,state,created_at,heartbeat_at"
            f") VALUES ({', '.join([placeholder] * 17)})",
            (
                execution_id,
                int(item_id) if item_id is not None else None,
                deployment_run_id,
                deployment_stage,
                deployment_member_item_id,
                transition_id,
                actor_id,
                session_id,
                digest,
                canonical(roster),
                canonical(execution_target),
                execution_target_digest,
                continues_execution_id,
                0,
                "active",
                now,
                now,
            ),
        )
    except db_backend.integrity_error_types(conn) as exc:
        execution = converge_plan_execution_insert_race(
            conn,
            item_id=item_id,
            transition_id=transition_id,
            deployment_run_id=deployment_run_id,
            deployment_stage=deployment_stage,
            deployment_member_item_id=deployment_member_item_id,
            actor_id=actor_id,
            session_id=session_id,
            digest=digest,
            cause=exc,
        )
        return {**execution, "remaining_requirement_count": remaining}
    conn.commit()
    return {
        **select_plan_execution(conn, execution_id, lock=False),
        "remaining_requirement_count": remaining,
    }
