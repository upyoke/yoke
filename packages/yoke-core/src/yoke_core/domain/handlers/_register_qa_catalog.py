"""Function registry entries for the QA catalog and plan management."""

from __future__ import annotations

from yoke_core.domain.handlers import qa_catalog_reads as _reads
from yoke_core.domain.handlers import qa_plan_edit as _edit
from yoke_core.domain.handlers import qa_plan_writes as _writes


def _read(
    registry,
    function_id,
    handler,
    request_model,
    response_model,
) -> None:
    registry.register(
        function_id,
        handler,
        request_model,
        response_model,
        stability="stable",
        owner_module="yoke_core.domain.handlers.qa_catalog_reads",
        target_kinds=["global"],
        side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=["project_scope_required"],
        adapter_status="live",
        claim_required_kind=None,
    )


def register(registry) -> None:
    _read(
        registry,
        "qa.method.list",
        _reads.handle_method_list,
        _reads.ProjectReadRequest,
        _reads.RowsResponse,
    )
    _read(
        registry,
        "qa.method.get",
        _reads.handle_method_get,
        _reads.MethodGetRequest,
        _reads.MethodGetResponse,
    )
    _read(
        registry,
        "qa.plan.list",
        _reads.handle_plan_list,
        _reads.ProjectReadRequest,
        _reads.RowsResponse,
    )
    _read(
        registry,
        "qa.plan.get",
        _reads.handle_plan_get,
        _reads.PlanGetRequest,
        _reads.PlanGetResponse,
    )
    _read(
        registry,
        "qa.activity.list",
        _reads.handle_activity_list,
        _reads.ActivityListRequest,
        _reads.ActivityListResponse,
    )
    registry.register(
        "qa.project_method.register",
        _writes.handle_project_method_register,
        _writes.ProjectMethodRegisterRequest,
        _writes.ProjectMethodRegisterResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.qa_plan_writes",
        target_kinds=["global"],
        side_effects=["qa_methods_upsert"],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=["project_scope_required", "registered_executor_only"],
        adapter_status="live",
        claim_required_kind=None,
        ambient_session_required=False,
    )
    registry.register(
        "qa.plan.create",
        _writes.handle_plan_create,
        _writes.PlanCreateRequest,
        _writes.PlanCreateResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.qa_plan_writes",
        target_kinds=["global"],
        side_effects=["qa_plans_insert"],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=["project_scope_required", "all_pass_policy"],
        adapter_status="live",
        claim_required_kind=None,
        ambient_session_required=False,
    )
    registry.register(
        "qa.plan.edit",
        _edit.handle_plan_edit,
        _edit.PlanEditRequest,
        _edit.PlanEditResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.qa_plan_edit",
        target_kinds=["global"],
        side_effects=["qa_plans_update", "qa_plan_cases_replace"],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[
            "project_scope_required",
            "compare_and_swap",
            "all_pass_policy",
            "snapshot_preserved",
        ],
        adapter_status="live",
        claim_required_kind=None,
        ambient_session_required=False,
    )
    registry.register(
        "qa.plan_cases.replace",
        _writes.handle_plan_cases_replace,
        _writes.PlanCasesReplaceRequest,
        _writes.PlanCasesReplaceResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.qa_plan_writes",
        target_kinds=["global"],
        side_effects=["qa_plan_cases_replace"],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=["project_scope_required", "snapshot_preserved"],
        adapter_status="live",
        claim_required_kind=None,
        ambient_session_required=False,
    )
    registry.register(
        "qa.project_default.set",
        _writes.handle_project_default_set,
        _writes.ProjectDefaultSetRequest,
        _writes.MutationResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.qa_plan_writes",
        target_kinds=["global"],
        side_effects=["qa_plan_project_defaults_upsert"],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=["project_scope_required", "workflow_exists"],
        adapter_status="live",
        claim_required_kind=None,
        ambient_session_required=False,
    )
    registry.register(
        "qa.item_plan.attach",
        _writes.handle_item_attach,
        _writes.ItemAttachRequest,
        _writes.MutationResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.qa_plan_writes",
        target_kinds=["item"],
        side_effects=["qa_plan_item_attachments_upsert"],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=["same_project", "claim_required"],
        adapter_status="live",
        claim_required_kind="item",
    )
    registry.register(
        "qa.plan.materialize",
        _writes.handle_materialize,
        _writes.MaterializeRequest,
        _writes.MutationResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.qa_plan_writes",
        target_kinds=["item"],
        side_effects=["qa_requirements_insert"],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=["snapshot_semantics", "idempotent", "claim_required"],
        adapter_status="live",
        claim_required_kind="item",
    )


__all__ = ["register"]
