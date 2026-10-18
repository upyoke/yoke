"""Record and read a deployment run's release phase timings."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome
from yoke_core.domain.handlers.deployment_common import error, run_id
from yoke_core.domain.handlers.deployment_run_execution import require_run_driver

RECORD_FUNCTION_ID = "deployment_runs.timings.record"
READ_FUNCTION_ID = "deployment_runs.timings"


class DeploymentRunTimingsRecordRequest(BaseModel):
    batch_id: str
    records: List[Dict[str, Any]]


class DeploymentRunTimingsRecordResponse(BaseModel):
    run_id: str
    recorded: int
    already_recorded: int


class DeploymentRunTimingsRequest(BaseModel):
    pass


class DeploymentRunTimingsResponse(BaseModel):
    run_id: str
    status: str
    records: List[Dict[str, Any]]
    steps: List[Dict[str, Any]]
    note: Optional[str] = None


def handle_deployment_run_timings_record(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    resolved = run_id(request, RECORD_FUNCTION_ID)
    if isinstance(resolved, HandlerOutcome):
        return resolved
    refused = require_run_driver(request, resolved)
    if refused is not None:
        return refused
    payload = request.payload or {}
    records = payload.get("records")
    if not isinstance(records, list):
        return error(
            "payload_invalid", "records must be a list", jsonpath="$.payload.records"
        )
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.deployment_run_timings import (
        TimingRecordInvalid,
        record_timings,
    )

    try:
        with connect() as conn:
            counts = record_timings(
                conn,
                run_id=resolved,
                batch_id=str(payload.get("batch_id") or ""),
                records=records,
            )
    except LookupError as exc:
        return error("not_found", str(exc), jsonpath="$.target.workflow_run_id")
    except TimingRecordInvalid as exc:
        return error("payload_invalid", str(exc), jsonpath="$.payload.records")
    return HandlerOutcome(
        result_payload={"run_id": resolved, **counts}, primary_success=True
    )


def handle_deployment_run_timings(request: FunctionCallRequest) -> HandlerOutcome:
    resolved = run_id(request, READ_FUNCTION_ID)
    if isinstance(resolved, HandlerOutcome):
        return resolved
    from yoke_core.domain.db_helpers import connect, query_scalar
    from yoke_core.domain.deployment_run_timings import run_timings, step_summary

    with connect() as conn:
        status = query_scalar(
            conn, "SELECT status FROM deployment_runs WHERE id=%s", (resolved,)
        )
        if status is None:
            return error(
                "not_found",
                f"deployment run {resolved!r} not found",
                jsonpath="$.target.workflow_run_id",
            )
        records = run_timings(conn, resolved)
    note = None
    if not records:
        note = (
            "no timings recorded: the run was never driven by a build that "
            "records timings, or every timing write was refused (the driver's "
            "capture names each refusal as `Deployment timing record refused`)"
        )
    return HandlerOutcome(
        result_payload={
            "run_id": resolved,
            "status": str(status),
            "records": records,
            "steps": step_summary(records),
            "note": note,
        },
        primary_success=True,
    )


def register(registry) -> None:
    common = dict(
        stability="stable",
        owner_module=__name__,
        target_kinds=["workflow_run"],
        emitted_event_names=["YokeFunctionCalled"],
        claim_required_kind=None,
        minimum_serving_version="next-release",
    )
    registry.register(
        RECORD_FUNCTION_ID,
        handle_deployment_run_timings_record,
        DeploymentRunTimingsRecordRequest,
        DeploymentRunTimingsRecordResponse,
        side_effects=["deployment_run_timings_insert"],
        guardrails=["run_driver_required", "idempotent_batch_replay"],
        adapter_status="internal",
        **common,
    )
    registry.register(
        READ_FUNCTION_ID,
        handle_deployment_run_timings,
        DeploymentRunTimingsRequest,
        DeploymentRunTimingsResponse,
        side_effects=[],
        guardrails=[],
        adapter_status="live",
        **common,
    )


__all__ = [
    "READ_FUNCTION_ID",
    "RECORD_FUNCTION_ID",
    "handle_deployment_run_timings",
    "handle_deployment_run_timings_record",
    "register",
]
