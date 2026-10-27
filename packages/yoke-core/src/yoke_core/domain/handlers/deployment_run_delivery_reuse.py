"""Run-driver authority to reuse a delivery the target already serves."""

from pydantic import BaseModel
from yoke_contracts.api.function_call import HandlerOutcome
from yoke_core.domain.deployment_run_delivery_reuse import (
    DELIVERY_REUSE_FUNCTION_ID as FUNCTION_ID,
)
from yoke_core.domain.handlers.deployment_common import error, run_id
from yoke_core.domain.handlers.deployment_run_execution import require_run_driver


class Request(BaseModel):
    stage_name: str


class Response(BaseModel):
    reused_run_id: str
    reason: str


def handle(request):
    resolved = run_id(request, FUNCTION_ID)
    if isinstance(resolved, HandlerOutcome):
        return resolved
    if refusal := require_run_driver(request, resolved):
        return refusal
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.deployment_run_delivery_reuse import reuse_delivery

    with connect() as conn:
        try:
            result = reuse_delivery(
                conn, resolved, str((request.payload or {}).get("stage_name") or "")
            )
        except (LookupError, ValueError) as exc:
            conn.rollback()
            return error("delivery_reuse_refused", str(exc))
        conn.commit()
    return HandlerOutcome(result_payload=result, primary_success=True)


def register(registry):
    registry.register(
        FUNCTION_ID,
        handle,
        Request,
        Response,
        stability="stable",
        owner_module=__name__,
        target_kinds=["workflow_run"],
        side_effects=["deployment_runs_update"],
        guardrails=["run_driver_required"],
        adapter_status="internal",
        claim_required_kind=None,
        minimum_serving_version="next-release",
    )
