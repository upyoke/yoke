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
from yoke_core.domain.qa_plan_execution_begin_admission import (
    PreparedRoster,
    admit_current_roster,
    begin_inputs,
    prepare_roster,
)
from yoke_core.domain.qa_plan_execution_begin_existing import (
    continuation_source,
    resume_existing,
)

from yoke_core.domain.qa_plan_execution_store import (
    QaPlanExecutionStateError,
    canonical,
    converge_plan_execution_insert_race,
    marker,
    select_plan_execution,
)
from yoke_core.domain.qa_plan_partition_custody import PartitionScope, admit_partition
from yoke_core.domain.qa_walk_authority import (
    require_walk_claim,
    require_walk_partition,
    walk_launch,
)
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
    expected_sha: str | None = None,
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
    partition: str | None = None,
) -> dict[str, Any]:
    """Admit unlocked roster reads under the run lock; resume retained custody."""
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
    authority_item = item_id or deployment_member_item_id
    launch = (
        walk_launch(conn, item_id=authority_item, session_id=session_id)
        if authority_item is not None else None
    )
    if launch is not None:
        require_walk_partition(launch, leg=transition_id or deployment_stage, key=partition)
    if launch is not None and item_id is not None:
        from yoke_core.domain.qa_case_source_lane import resolve_walk_lane

        require_walk_claim(conn, item_id=item_id, launch=launch, lock=True)
        lane = resolve_walk_lane(
            conn, item_id=item_id, session_id=launch.requester,
            expected_branch=expected_branch, expected_sha=expected_sha,
        )
        checkout_path = lane["lane_path"]
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
            partition=partition,
            source_session_id=launch.requester if launch is not None else None,
        )

    # Every roster read runs before the run lock; it covers the re-check and write.
    prepared = prepare()
    if not isinstance(prepared, PreparedRoster):
        from yoke_core.domain.deployment_qa_resettlement import resettle_execution

        conn.commit()
        resettle_execution(conn, prepared)
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
    scope = PartitionScope(item_id, transition_id, deployment_run_id, deployment_stage, deployment_member_item_id)
    continues_execution_id = None
    for _attempt in range(RUN_READ_ATTEMPTS + 1):
        if continue_mission:
            continues_execution_id = continuation_source(
                conn, subject_key, prepared, continuation_execution_id
            )
        if launch is not None:
            require_walk_claim(conn, item_id=authority_item, launch=launch, lock=True)
        resumed, retired = resume_existing(
            conn, subject_key, prepared, actor_id=actor_id, partition=partition,
            requirement_id=requirement_id,
        )
        if resumed is not None:
            return resumed
        if not retired and (item_id is not None or deployment_stage is not None):
            retired = admit_partition(
                conn, scope, key=prepared.partition or "<selected>",
                roster=prepared.roster, session_id=session_id,
            )
            if retired:
                conn.commit()
        if not retired:
            break
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

    roster, remaining, digest = prepared.roster, prepared.remaining, prepared.digest
    execution_target = prepared.execution_target
    execution_target_digest = prepared.execution_target_digest
    execution_id = str(uuid4())
    from yoke_core.domain.qa_environment_served_build import observe_build
    build = observe_build(conn, execution_target)
    now = utc_now()
    placeholder = marker(conn)
    try:
        conn.execute(
            "INSERT INTO qa_plan_executions("
            "id,item_id,deployment_run_id,deployment_stage,"
            "deployment_member_item_id,transition_id,actor_id,session_id,"
            "roster_digest,"
            "roster_json,execution_target_json,execution_target_digest,served_build_sha,served_build_status,"
            "continues_execution_id,requesting_member_item_id,"
            "cursor_ordinal,state,created_at,heartbeat_at"
            f") VALUES ({', '.join([placeholder] * 20)})",
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
                build["served_build_sha"], build["served_build_status"],
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
            execution_target_digest=execution_target_digest,
        )
        return {**execution, "remaining_requirement_count": remaining}
    conn.commit()
    return {
        **select_plan_execution(conn, execution_id, lock=False),
        "remaining_requirement_count": remaining,
    }
