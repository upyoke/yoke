"""Register project-scoped operations used by deployment execution."""

from yoke_core.domain.handlers import deployment_qa_stage_relay as qa_stage_relay
from yoke_core.domain.handlers import deployment_run_execution as execution
from yoke_core.domain.handlers import deployment_run_execution_qa as qa
from yoke_core.domain.handlers import deployment_run_execution_receipt as receipt


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


__all__ = ["register"]
