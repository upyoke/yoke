"""Registered steering reconciliation of a stranded QA plan execution."""

from pydantic import BaseModel, Field
from psycopg.errors import LockNotAvailable, QueryCanceled

from yoke_contracts.api.function_call import HandlerOutcome
from yoke_core.domain.handlers.qa_plan_execution import _error, _parse
from yoke_core.domain.handlers.qa_plan_execution_models import PlanExecutionStateRequest
from yoke_core.domain.qa_plan_execution_abort_reason import ABORT_REASON_MAX_LENGTH


class PlanExecutionReconcileRequest(PlanExecutionStateRequest):
    reason: str = Field(min_length=1, max_length=ABORT_REASON_MAX_LENGTH, pattern=r"\S")


class PlanExecutionReconcileResponse(BaseModel):
    execution_id: str
    reconciliation_id: str
    outcome: str
    state: str
    prior_state: str
    prior_session_id: str | None = None
    released_lease_ids: list[int]
    review_bundle_id: str | None = None
    next_command: str | None = None


def handle_execution_reconcile(request):
    parsed = _parse(PlanExecutionReconcileRequest, request.payload)
    if isinstance(parsed, HandlerOutcome):
        return parsed
    if request.target.kind != "global" or not request.target.project_id:
        return _error(
            "target_invalid",
            "qa.plan_execution.reconcile requires a project target: pass --project P",
            "$.target",
        )
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.project_identity import resolve_project_id
    from yoke_core.domain.qa_plan_execution_reconcile import reconcile_execution

    conn = connect()
    try:
        result = reconcile_execution(
            conn,
            parsed.execution_id,
            project_id=resolve_project_id(conn, str(request.target.project_id)),
            actor_id=request.actor.actor_id,
            session_id=request.actor.session_id,
            reason=parsed.reason,
        )
    except (LockNotAvailable, QueryCanceled):
        conn.rollback()
        return _error(
            "qa_reconcile_busy",
            "qa_reconcile_busy: the execution row or its leases stayed locked past "
            "the query budget; nothing changed. Inspect contention, then retry the "
            "same reconcile command",
            "$.payload.execution_id",
        )
    except (LookupError, ValueError) as exc:
        conn.rollback()
        return _error("qa_reconcile_refused", str(exc), "$.payload.execution_id")
    finally:
        conn.close()
    return HandlerOutcome(primary_success=True, result_payload=result)


def register(registry):
    registry.register(
        "qa.plan_execution.reconcile",
        handle_execution_reconcile,
        PlanExecutionReconcileRequest,
        PlanExecutionReconcileResponse,
        stability="stable",
        owner_module=__name__,
        target_kinds=["global"],
        minimum_serving_version="next-release",
        side_effects=[
            "qa_plan_execution_write",
            "coordination_claim_heartbeat_or_release",
            "qa_plan_execution_reconciliation_write",
        ],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[
            "steering_seat_required",
            "stale_owner_required",
            "host_recovery_proof_required",
            "durable_reconciliation_receipt",
        ],
        adapter_status="live",
        claim_required_kind="steering",
        ambient_session_required=True,
    )
