"""Register project-scoped operations used by deployment execution."""

from typing import Any, Optional

from pydantic import BaseModel

from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome
from yoke_core.domain.deployment_run_driver_attachment import (
    ATTACH_FUNCTION_ID,
    FOR_CAPTURE_FUNCTION_ID,
    RELEASE_FUNCTION_ID,
    DriverAlreadyAttached,
    VALID_PHASES,
    attach_driver,
    live_attachment_for_capture,
    release_driver,
)
from yoke_core.domain.handlers import deployment_qa_stage_relay as qa_stage_relay
from yoke_core.domain.handlers import deployment_run_execution as execution
from yoke_core.domain.handlers import deployment_run_execution_qa as qa
from yoke_core.domain.handlers import deployment_run_execution_receipt as receipt
from yoke_core.domain.handlers.deployment_common import error, require_global, run_id


class AttachDriverRequest(BaseModel):
    phase: str
    pid: int
    progress_capture: str = ""


class AttachDriverResponse(BaseModel):
    run_id: str
    recorded: bool
    driver: dict[str, Any] = {}


class ReleaseDriverRequest(BaseModel):
    pid: int


class ReleaseDriverResponse(BaseModel):
    run_id: str
    released: bool


class DriverForCaptureRequest(BaseModel):
    progress_capture: str


class DriverForCaptureResponse(BaseModel):
    driver: Optional[dict[str, Any]] = None


def handle_attach_driver(request: FunctionCallRequest) -> HandlerOutcome:
    resolved = run_id(request, ATTACH_FUNCTION_ID)
    if isinstance(resolved, HandlerOutcome):
        return resolved
    payload = request.payload or {}
    phase = str(payload.get("phase") or "").strip()
    try:
        pid = int(payload.get("pid") or 0)
    except (TypeError, ValueError):
        pid = 0
    if phase not in VALID_PHASES or pid <= 0:
        return error("payload_invalid", "phase and pid are required")
    session_id = str(request.actor.session_id or "").strip()
    if not session_id:
        return error("unauthenticated", "a session is required to attach a driver")
    if refusal := execution._require_execution_lock(request, resolved):
        return refusal
    from yoke_core.domain.db_helpers import connect

    with connect() as conn:
        try:
            recorded = attach_driver(
                conn,
                resolved,
                session_id=session_id,
                pid=pid,
                phase=phase,
                progress_capture=str(payload.get("progress_capture") or ""),
            )
        except LookupError as exc:
            conn.rollback()
            return error("not_found", str(exc))
        except DriverAlreadyAttached as exc:
            conn.rollback()
            return error("driver_already_attached", str(exc))
        except ValueError as exc:
            conn.rollback()
            return error("payload_invalid", str(exc))
        conn.commit()
    return HandlerOutcome(
        result_payload={
            "run_id": resolved,
            "recorded": recorded is not None,
            "driver": recorded.as_dict() if recorded is not None else {},
        },
        primary_success=True,
    )


def handle_release_driver(request: FunctionCallRequest) -> HandlerOutcome:
    resolved = run_id(request, RELEASE_FUNCTION_ID)
    if isinstance(resolved, HandlerOutcome):
        return resolved
    try:
        pid = int((request.payload or {}).get("pid") or 0)
    except (TypeError, ValueError):
        pid = 0
    session_id = str(request.actor.session_id or "").strip()
    if not session_id:
        return error("unauthenticated", "a session is required to release a driver")
    if pid <= 0:
        return error("payload_invalid", "pid is required")
    if refusal := execution._require_execution_lock(request, resolved):
        return refusal
    from yoke_core.domain.db_helpers import connect

    with connect() as conn:
        released = release_driver(conn, resolved, session_id=session_id, pid=pid)
        conn.commit()
    return HandlerOutcome(
        result_payload={"run_id": resolved, "released": released},
        primary_success=True,
    )


def handle_driver_for_capture(request: FunctionCallRequest) -> HandlerOutcome:
    if invalid := require_global(request, FOR_CAPTURE_FUNCTION_ID):
        return invalid
    capture = str((request.payload or {}).get("progress_capture") or "").strip()
    if not capture:
        return error("payload_invalid", "progress_capture is required")
    from yoke_core.domain.db_helpers import connect, iso8601_now

    with connect() as conn:
        found = live_attachment_for_capture(
            conn, progress_capture=capture, now=iso8601_now()
        )
    return HandlerOutcome(
        result_payload={"driver": None if found is None else found.as_dict()},
        primary_success=True,
    )


def register(registry) -> None:
    registry.register(
        "deployment_runs.execution.context",
        execution.handle_deployment_execution_context,
        execution.DeploymentExecutionContextRequest,
        execution.DeploymentExecutionContextResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.deployment_run_execution",
        target_kinds=["workflow_run"],
        side_effects=["deployment_run_items_insert"],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[
            "deploy_lock_required",
            "created_only_membership",
            "item_workflow_binding",
        ],
        adapter_status="internal",
        claim_required_kind=None,
    )
    registry.register(
        "deployment_runs.execution.update",
        execution.handle_deployment_execution_update,
        execution.DeploymentExecutionUpdateRequest,
        execution.DeploymentExecutionUpdateResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.deployment_run_execution",
        target_kinds=["workflow_run"],
        side_effects=["deployment_runs_update"],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=["deploy_lock_required", "execution_fields_only"],
        adapter_status="internal",
        claim_required_kind=None,
    )
    for function_id, handler, request_model, response_model, side_effects in (
        (
            "deployment_runs.execution.ephemeral_qa_ready",
            qa.handle_deployment_execution_ephemeral_qa_ready,
            qa.DeploymentExecutionEphemeralQaReadyRequest,
            qa.DeploymentExecutionEphemeralQaReadyResponse,
            [],
        ),
        (
            "deployment_runs.execution.qa_seed",
            qa.handle_deployment_execution_qa_seed,
            qa.DeploymentExecutionQaSeedRequest,
            qa.DeploymentExecutionQaSeedResponse,
            ["qa_requirements_insert", "deployment_run_qa_insert"],
        ),
        (
            "deployment_runs.execution.qa_record",
            qa.handle_deployment_execution_qa_record,
            qa.DeploymentExecutionQaRecordRequest,
            qa.DeploymentExecutionQaRecordResponse,
            ["qa_runs_insert", "deployment_run_qa_update"],
        ),
        (
            "deployment_runs.execution.qa_pending",
            qa.handle_deployment_execution_qa_pending,
            qa.DeploymentExecutionQaPendingRequest,
            qa.DeploymentExecutionQaPendingResponse,
            [],
        ),
    ):
        registry.register(
            function_id,
            handler,
            request_model,
            response_model,
            stability="stable",
            owner_module="yoke_core.domain.handlers.deployment_run_execution_qa",
            target_kinds=["workflow_run"],
            side_effects=side_effects,
            emitted_event_names=["YokeFunctionCalled"],
            guardrails=["deploy_lock_required"],
            adapter_status="internal",
            claim_required_kind=None,
        )
    for function_id, handler, request_model, response_model, side_effects in (
        (
            "deployment_runs.execution.stage_receipt_allocate",
            receipt.handle_deployment_execution_stage_receipt_allocate,
            receipt.DeploymentExecutionStageReceiptAllocateRequest,
            receipt.DeploymentExecutionStageReceiptAllocateResponse,
            ["deployment_stage_receipts_insert"],
        ),
        (
            "deployment_runs.execution.stage_receipt_complete",
            receipt.handle_deployment_execution_stage_receipt_complete,
            receipt.DeploymentExecutionStageReceiptCompleteRequest,
            receipt.DeploymentExecutionStageReceiptCompleteResponse,
            ["deployment_stage_receipts_update"],
        ),
        (
            "deployment_runs.execution.stage_receipt_latest",
            receipt.handle_deployment_execution_stage_receipt_latest,
            receipt.DeploymentExecutionStageReceiptLatestRequest,
            receipt.DeploymentExecutionStageReceiptLatestResponse,
            [],
        ),
    ):
        registry.register(
            function_id,
            handler,
            request_model,
            response_model,
            stability="stable",
            owner_module="yoke_core.domain.handlers.deployment_run_execution_receipt",
            target_kinds=["workflow_run"],
            side_effects=side_effects,
            emitted_event_names=["YokeFunctionCalled"],
            guardrails=["deploy_lock_required"],
            adapter_status="internal",
            claim_required_kind=None,
        )
    registry.register(
        qa_stage_relay.DISPATCH_FUNCTION_ID,
        qa_stage_relay.handle_deployment_qa_stage_dispatch,
        qa_stage_relay.DeploymentQaStageDispatchRequest,
        qa_stage_relay.DeploymentQaStageDispatchResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.deployment_qa_stage_relay",
        target_kinds=["workflow_run"],
        # Deriving on the serving build, not the driver: a release driver
        # runs the candidate revision while the control plane it reads
        # still runs the deployed one, so this evaluates on whichever
        # process actually serves the database.
        side_effects=["qa_requirements_insert"],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=["deploy_lock_required"],
        adapter_status="internal",
        claim_required_kind=None,
    )
    registry.register(
        qa_stage_relay.RESUME_FUNCTION_ID,
        qa_stage_relay.handle_deployment_qa_stage_resume_refusals,
        qa_stage_relay.DeploymentQaStageResumeRefusalsRequest,
        qa_stage_relay.DeploymentQaStageResumeRefusalsResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.deployment_qa_stage_relay",
        target_kinds=["workflow_run"],
        side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=["deploy_lock_required"],
        adapter_status="internal",
        claim_required_kind=None,
    )
    registry.register(
        ATTACH_FUNCTION_ID,
        handle_attach_driver,
        AttachDriverRequest,
        AttachDriverResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers._register_deployment_execution",
        target_kinds=["workflow_run"],
        side_effects=["deployment_runs_update"],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=["deploy_lock_required"],
        adapter_status="internal",
        claim_required_kind=None,
        minimum_serving_version="next-release",
    )
    registry.register(
        RELEASE_FUNCTION_ID,
        handle_release_driver,
        ReleaseDriverRequest,
        ReleaseDriverResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers._register_deployment_execution",
        target_kinds=["workflow_run"],
        side_effects=["deployment_runs_update"],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=["deploy_lock_required"],
        adapter_status="internal",
        claim_required_kind=None,
        minimum_serving_version="next-release",
    )
    registry.register(
        FOR_CAPTURE_FUNCTION_ID,
        handle_driver_for_capture,
        DriverForCaptureRequest,
        DriverForCaptureResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers._register_deployment_execution",
        target_kinds=["global"],
        side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[],
        adapter_status="internal",
        claim_required_kind=None,
        minimum_serving_version="next-release",
    )


__all__ = ["register"]
