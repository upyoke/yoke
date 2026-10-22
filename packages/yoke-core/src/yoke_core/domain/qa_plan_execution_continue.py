"""Continue one named stale walk through the existing subject admission."""

from yoke_core.domain.qa_plan_execution_store import (
    QaPlanExecutionStateError,
    plan_execution_view,
)


def continue_execution(conn, execution, parsed, actor):
    # Ownership was checked with the execution locked. Release that read lock
    # before begin takes the subject lock; begin rechecks the exact source.
    conn.rollback()
    common = dict(
        actor_id=actor.actor_id,
        session_id=actor.session_id,
        machine=parsed.machine,
        continue_mission=True,
        continuation_execution_id=str(execution["id"]),
    )
    if execution.get("standalone_plan_id") is not None:
        from yoke_core.domain.qa_standalone_execution import begin_standalone_execution

        case = execution["roster"][0]
        continued = begin_standalone_execution(
            conn,
            plan=str(execution["standalone_plan_id"]),
            project=case["project"],
            source_revision=case.get("standalone_source_revision"),
            source_ref=case.get("standalone_source_ref"),
            checkout_path=case.get("standalone_checkout_path"),
            **common,
        )
    else:
        from yoke_core.domain.qa_plan_execution_begin import begin_plan_execution
        from yoke_core.domain.deployment_qa_takeover_identity import (
            read_execution_subject,
        )

        from yoke_core.domain.qa_plan_execution_begin_admission import (
            BeginInputsChanged,
            begin_inputs,
        )

        run_id = execution.get("deployment_run_id")
        inputs = (
            begin_inputs(conn, run_id, execution.get("deployment_stage"))
            if run_id
            else None
        )
        subject = (
            read_execution_subject(
                conn, execution, execution["execution_target"], require_active=True
            )
            if execution.get("deployment_stage")
            else None
        )
        try:
            continued = begin_plan_execution(
                conn,
                item_id=execution.get("item_id"),
                transition_id=execution.get("transition_id"),
                deployment_run_id=execution.get("deployment_run_id"),
                deployment_stage=execution.get("deployment_stage"),
                deployment_member_item_id=execution.get("deployment_member_item_id"),
                checkout_path=parsed.checkout_path,
                expected_branch=parsed.expected_branch,
                _deployment_subject=subject,
                _run_inputs=inputs,
                **common,
            )
        except BeginInputsChanged as exc:
            conn.rollback()
            raise QaPlanExecutionStateError(
                "qa_continuation_source_changed: admission changed; retry the same "
                "execution id after its current owner settles"
            ) from exc
    return plan_execution_view(conn, continued)
