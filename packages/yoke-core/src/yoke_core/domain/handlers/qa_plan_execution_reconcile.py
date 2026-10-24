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


def _require_operator(conn, request, project_id):
    """A session needs a covering steering seat; no session needs org admin."""
    if request.actor.session_id:
        from yoke_core.domain.session_steering_authority import require_operator_seat

        require_operator_seat(
            conn,
            caller_session_id=request.actor.session_id,
            project_id=project_id,
            action="QA execution reconciliation",
        )
        return
    from yoke_core.domain.actor_permissions import PERM_ORG_ADMIN, PermissionDenied
    from yoke_core.domain.control_plane_authority import (
        require_control_plane_permission,
    )

    if not str(request.actor.actor_id or "").isdigit():
        raise PermissionDenied("no authenticated actor")
    require_control_plane_permission(
        conn, actor_id=int(request.actor.actor_id), permission_key=PERM_ORG_ADMIN
    )


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

    from yoke_core.domain.actor_permissions import PermissionDenied
    from yoke_core.domain.sessions_analytics_core import SessionError

    conn = connect()
    try:
        project_id = resolve_project_id(conn, str(request.target.project_id))
        _require_operator(conn, request, project_id)
        result = reconcile_execution(
            conn,
            parsed.execution_id,
            project_id=project_id,
            actor_id=request.actor.actor_id,
            session_id=request.actor.session_id or None,
            reason=parsed.reason,
        )
    except SessionError as exc:
        conn.rollback()
        return _error(exc.code, exc.message, "$.actor")
    except PermissionDenied:
        conn.rollback()
        return _error(
            "operator_permission_required",
            "operator_permission_required: a call without a session must come "
            "from the control-plane organization administrator; otherwise run "
            "it from a session holding a steering seat (yoke claims steering "
            "acquire --project P --reason TEXT). Nothing changed.",
            "$.actor",
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
        guardrails=[
            "steering_seat_required",
            "control_plane_operator_without_session",
            "stale_owner_required",
            "host_recovery_proof_required",
            "durable_reconciliation_receipt",
        ],
        adapter_status="live",
        claim_required_kind=None,
        ambient_session_required=False,
    )
