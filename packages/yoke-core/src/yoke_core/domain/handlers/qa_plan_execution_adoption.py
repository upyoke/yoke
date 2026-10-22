"""Registered audited QA execution adoption after worker restaffing."""

from pydantic import BaseModel, Field
from psycopg.errors import LockNotAvailable, QueryCanceled

from yoke_contracts.api.function_call import HandlerOutcome
from yoke_core.domain.handlers.qa_plan_execution import _error, _parse, _subject
from yoke_core.domain.handlers.qa_plan_execution_models import PlanExecutionStateRequest


class PlanExecutionAdoptRequest(PlanExecutionStateRequest):
    reason: str = Field(min_length=1, max_length=2000, pattern=r"\S")


class PlanExecutionAdoptResponse(BaseModel):
    execution_id: str
    state: str
    adoption_id: str | None = None
    previous_session_id: str | None = None
    session_id: str


def handle_execution_adopt(request):
    parsed = _parse(PlanExecutionAdoptRequest, request.payload)
    if isinstance(parsed, HandlerOutcome):
        return parsed
    subject = _subject(request, request.function)
    if isinstance(subject, HandlerOutcome):
        return subject
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.qa_plan_execution_adoption import adopt_execution

    from yoke_core.domain.qa_plan_execution_reentry import bound_checkin_queries

    conn = connect()
    try:
        bound_checkin_queries(conn)
        from yoke_core.domain.qa_execution_request_identity import resolve_execution_request
        from yoke_core.domain.qa_plan_execution_store import lock_plan_execution

        execution = lock_plan_execution(conn, parsed.execution_id)
        resolved = resolve_execution_request(conn, request, execution)
        subject = resolved.target.item_id, resolved.target.deployment_run_id
        result = adopt_execution(
            conn,
            parsed.execution_id,
            item_id=subject[0],
            deployment_run_id=subject[1],
            actor_id=request.actor.actor_id,
            session_id=request.actor.session_id,
            reason=parsed.reason,
        )
    except (LockNotAvailable, QueryCanceled):
        conn.rollback()
        return _error(
            "qa_adoption_busy",
            "qa_adoption_busy: ownership validation exceeded its lock/query budget; "
            "preserve the execution, inspect contention, then retry the same adoption",
            "$.payload.execution_id",
        )
    except ValueError as exc:
        conn.rollback()
        return _error("qa_adoption_refused", str(exc), "$.payload.execution_id")
    finally:
        conn.close()
    return HandlerOutcome(primary_success=True, result_payload=result)


def register(registry):
    registry.register(
        "qa.plan_execution.adopt",
        handle_execution_adopt,
        PlanExecutionAdoptRequest,
        PlanExecutionAdoptResponse,
        stability="stable",
        owner_module=__name__,
        target_kinds=["item", "global"],
        minimum_serving_version="next-release",
        side_effects=["qa_plan_execution_write", "qa_plan_execution_adoption_write"],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[
            "project_scope_required",
            "item_work_holder",
            "ended_predecessor",
            "durable_adoption_receipt",
        ],
        adapter_status="live",
        claim_required_kind="qa_subject",
        ambient_session_required=True,
    )
