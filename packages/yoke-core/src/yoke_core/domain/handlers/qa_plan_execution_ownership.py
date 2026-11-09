"""Validate execution custody before a registered execution mutation."""

from typing import Any

from psycopg.errors import LockNotAvailable, QueryCanceled
from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome
from yoke_core.domain.handlers.qa_plan_execution_models import PlanExecutionStateRequest
from yoke_core.domain.machine_qa_plan_case_request import (
    target_plan_subject as _subject,
)


def _error(code, message, jsonpath):
    from yoke_core.domain.handlers.qa_plan_execution import _error as outcome

    return outcome(code, message, jsonpath)


def _owned_execution(
    request: FunctionCallRequest,
    parsed: PlanExecutionStateRequest,
    *,
    abandoning: bool = False,
) -> tuple[Any, dict[str, Any]] | HandlerOutcome:
    target = _subject(request, request.function)
    if isinstance(target, HandlerOutcome):
        return target
    item_id, deployment_run_id = target
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.qa_plan_execution_reentry import (
        BOUNDED_CHECKIN_FUNCTIONS,
        bound_checkin_queries,
        bounded_refusal,
    )
    from yoke_core.domain.qa_plan_execution_state import (
        lock_plan_execution,
        plan_execution_abort_authority,
        require_plan_execution_owner,
    )

    conn = connect()
    try:
        if request.function in BOUNDED_CHECKIN_FUNCTIONS:
            bound_checkin_queries(conn)
        execution = lock_plan_execution(conn, parsed.execution_id)
        from yoke_core.domain.qa_execution_request_identity import (
            resolve_execution_request,
        )

        request = resolve_execution_request(conn, request, execution)
        item_id, deployment_run_id = (
            request.target.item_id,
            request.target.deployment_run_id,
        )
        if request.target.kind == "global":
            from yoke_core.domain.qa_standalone_execution import (
                require_standalone_project,
            )

            require_standalone_project(conn, execution, str(request.target.project_id))
        subject = {
            "item_id": item_id,
            "deployment_run_id": deployment_run_id,
            "actor_id": request.actor.actor_id,
            "session_id": request.actor.session_id,
        }
        if abandoning:
            plan_execution_abort_authority(conn, execution, **subject)
        else:
            from yoke_core.domain.deployment_qa_resettlement import completed_replay

            require_plan_execution_owner(
                execution,
                conn=conn,
                deployment_stage=execution.get("deployment_stage"),
                deployment_member_item_id=execution.get("deployment_member_item_id"),
                completed_replay=completed_replay(request, execution),
                reviewing=request.function
                in {"qa.plan_review.begin", "qa.plan_review.submit"},
                **subject,
            )

    except (ValueError, LockNotAvailable, QueryCanceled) as exc:
        conn.rollback()
        conn.close()
        message = bounded_refusal(exc, step="execution validation")
        return _error("plan_execution_invalid", message, "$.payload.execution_id")
    return conn, execution
