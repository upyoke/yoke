"""Creation and resumption of durable ordered QA executions."""

from __future__ import annotations

from typing import Any

from uuid import uuid4

from yoke_core.domain import db_backend
from yoke_core.domain.deployment_runs_lock import (
    RUN_READ_ATTEMPTS,
    DeploymentRunChanging,
)
from yoke_contracts.timestamps import utc_now
from yoke_core.domain.db_helpers import instant_parameter
from yoke_core.domain.qa_plan_execution_authority import plan_execution_is_abandoned
from yoke_core.domain.qa_plan_execution_begin_admission import (
    PreparedRoster,
    admit_current_roster,
    begin_inputs,
    prepare_roster,
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
    canonical,
    converge_plan_execution_insert_race,
    live_plan_execution_id,
    lock_plan_execution,
    marker,
    resume_owned_plan_execution,
    same_owner,
    select_plan_execution,
)
from yoke_core.domain.qa_plan_execution_target_snapshot import (
    require_execution_target,
)
from yoke_core.domain.qa_plan_execution_roster_change import (
    retire_unstarted_changed_roster,
)
from yoke_core.domain.qa_stage_execution_holders import admit_stage_roster

from yoke_core.domain.workflow_item_binding_lock import (
    lock_item_workflow_bindings,
    rollback_workflow_binding_write_errors,
)


from yoke_core.domain.deployment_qa_shared_execution import route_shared_plan_execution


@route_shared_plan_execution
@rollback_workflow_binding_write_errors
def begin_plan_execution(
    conn: Any,
    *,
    item_id: int | None = None,
    transition_id: str | None = None,
    deployment_run_id: str | None = None,
    deployment_stage: str | None = None,
    deployment_member_item_id: int | None = None,
    checkout_path: str | None = None,
    expected_branch: str | None = None,
    test_machine: str | None = None,
    continue_mission: bool = False,
    continuation_execution_id: str | None = None,
    actor_id: str | None,
    session_id: str,
    _deployment_subject: dict | None = None,
    _requesting_member_item_id: int | None = None,
    _run_inputs: str | None = None,
    plan: str | None = None,
    requirement_id: int | None = None,
) -> dict[str, Any]:
    """Create or resume the subject's execution after unlocked roster admission.

    The run lock rechecks ``begin_inputs`` after roster reads. A changed
    member input returns to the router for an unlocked retry. Continuations
    preserve the stale-settled mission's host without applying a baseline.
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
        from yoke_core.domain.deployment_qa_execution_target import (
            deployment_qa_execution_target,
        )
        from yoke_core.domain.deployment_qa_stage_contract import (
            deployment_qa_stage_subject,
        )

        subject = _deployment_subject or deployment_qa_stage_subject(
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
    # The member the run lock admits; a shared group walks for its requester.
    admitted = (
        deployment_member_item_id
        if deployment_member_item_id is not None
        else _requesting_member_item_id
    )
    # Stage-wide executions run one per session; the run lock keeps them disjoint.
    stage_wide = deployment_stage is not None and deployment_member_item_id is None
    locks_run = deployment_run_id is not None and (admitted is not None or stage_wide)
    run_inputs = (
        begin_inputs(conn, str(deployment_run_id), deployment_stage)
        if locks_run and admitted is None
        else _run_inputs
    )

    def prepare() -> PreparedRoster | dict[str, Any]:
        return prepare_roster(
            conn,
            item_id=item_id,
            transition_id=transition_id,
            deployment_run_id=deployment_run_id,
            deployment_stage=deployment_stage,
            deployment_member_item_id=deployment_member_item_id,
            expected_target=expected_deployment_target,
            expected_target_digest=expected_deployment_target_digest,
            plan=plan,
            requirement_id=requirement_id,
            host_capability_kinds=host_capabilities,
            checkout_path=checkout_path,
            expected_branch=expected_branch,
            session_id=session_id,
            test_machine=test_machine,
        )

    # Every roster read runs before the run lock; it covers the re-check and write.
    prepared = prepare()
    if not isinstance(prepared, PreparedRoster):
        return prepared
    if locks_run:
        prepared = admit_current_roster(
            conn,
            str(deployment_run_id),
            deployment_stage,
            admitted,
            run_inputs,
            prepared,
            prepare,
        )
        if not isinstance(prepared, PreparedRoster):
            return prepared
    subject_key = dict(
        item_id=item_id,
        transition_id=transition_id,
        deployment_run_id=deployment_run_id,
        deployment_stage=deployment_stage,
        deployment_member_item_id=deployment_member_item_id,
        session_id=session_id,
    )
    existing_id = live_plan_execution_id(conn, **subject_key)

    def continuation_source():
        return resolve_continuation_source(
            conn,
            live_execution_id=live_plan_execution_id(conn, **subject_key),
            expected_execution_id=continuation_execution_id,
            **subject_key,
        )

    continues_execution_id = continuation_source() if continue_mission else None
    admission_repeated = False
    retired = False
    if existing_id is not None:
        existing = lock_plan_execution(conn, existing_id)
        if requirement_id is not None and [
            int(r["requirement_id"]) for r in existing["roster"]
        ] != [requirement_id]:
            from yoke_core.domain.qa_plan_execution_roster_change import abort_command

            raise QaPlanExecutionStateError(
                f"qa_single_case_scope_busy: another roster is live; finish it or use `{abort_command(conn, existing)}`, then retry the case"
            )
        if existing["state"] in {
            "active",
            "waiting",
            "walking",
            "awaiting_walk_review",
        }:
            if same_owner(existing, actor_id=actor_id, session_id=session_id):
                require_execution_target(existing)
                if not retire_unstarted_changed_roster(
                    conn, existing, digest=prepared.digest
                ):
                    return {
                        **resume_owned_plan_execution(
                            conn, existing, digest=prepared.digest
                        ),
                        "remaining_requirement_count": prepared.remaining,
                    }
            elif plan_execution_is_abandoned(conn, existing):
                finish_plan_execution(
                    conn,
                    existing,
                    state="aborted",
                    reason=STALE_PLAN_EXECUTION_REASON,
                )
            else:
                conn.rollback()
                raise QaPlanExecutionStateError(
                    "another actor or session owns the active QA plan execution"
                )
            retired = True
    for _attempt in range(RUN_READ_ATTEMPTS + 1):
        if stage_wide and admit_stage_roster(
            conn,
            prepared.roster,
            deployment_run_id=str(deployment_run_id),
            deployment_stage=str(deployment_stage),
            session_id=session_id,
        ):
            retired = True
        if not retired:
            break
        retired = False
        admission_repeated = True
        # Retiring a live execution committed; read the roster again first.
        if item_id is not None:
            lock_item_workflow_bindings(conn, (int(item_id),))
        inputs = (
            begin_inputs(conn, str(deployment_run_id), deployment_stage)
            if locks_run
            else None
        )
        prepared = prepare()
        if not isinstance(prepared, PreparedRoster):
            return prepared
        if locks_run:
            prepared = admit_current_roster(
                conn,
                str(deployment_run_id),
                deployment_stage,
                admitted,
                inputs,
                prepared,
                prepare,
            )
            if not isinstance(prepared, PreparedRoster):
                return prepared
    else:
        raise DeploymentRunChanging(str(deployment_run_id))

    if continue_mission and admission_repeated:
        continues_execution_id = continuation_source()
    roster, remaining, digest = prepared.roster, prepared.remaining, prepared.digest
    execution_target = prepared.execution_target
    execution_target_digest = prepared.execution_target_digest
    execution_id = str(uuid4())
    now = utc_now()
    placeholder = marker(conn)
    try:
        conn.execute(
            "INSERT INTO qa_plan_executions("
            "id,item_id,deployment_run_id,deployment_stage,"
            "deployment_member_item_id,transition_id,actor_id,session_id,"
            "roster_digest,"
            "roster_json,execution_target_json,execution_target_digest,"
            "continues_execution_id,requesting_member_item_id,"
            "cursor_ordinal,state,created_at,heartbeat_at"
            f") VALUES ({', '.join([placeholder] * 18)})",
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
                _requesting_member_item_id,
                0,
                "active",
                instant_parameter(conn, now),
                instant_parameter(conn, now),
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
