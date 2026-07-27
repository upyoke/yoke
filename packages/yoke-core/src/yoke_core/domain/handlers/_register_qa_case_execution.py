"""Function registry leaf for shared QA plan-case execution."""

from __future__ import annotations

from yoke_core.domain.handlers import qa_case_execution as _case
from yoke_core.domain.handlers import qa_plan_execution as _plan


def register(registry) -> None:
    for function_id, handler, request_model in (
        (
            "qa.plan_execution.begin",
            _plan.handle_plan_execution_begin,
            _plan.PlanExecutionBeginRequest,
        ),
        (
            "qa.plan_execution.heartbeat",
            _plan.handle_plan_execution_heartbeat,
            _plan.PlanExecutionStateRequest,
        ),
        (
            "qa.plan_execution.advance",
            _plan.handle_plan_execution_advance,
            _plan.PlanExecutionAdvanceRequest,
        ),
        (
            "qa.plan_execution.complete",
            _plan.handle_plan_execution_complete,
            _plan.PlanExecutionStateRequest,
        ),
        (
            "qa.plan_execution.abort",
            _plan.handle_plan_execution_abort,
            _plan.PlanExecutionAbortRequest,
        ),
    ):
        registry.register(
            function_id,
            handler,
            request_model,
            _plan.PlanExecutionStateResponse,
            stability="stable",
            owner_module="yoke_core.domain.handlers.qa_plan_execution",
            target_kinds=["item"],
            side_effects=[
                "qa_plan_execution_write",
                "coordination_lease_heartbeat_or_release",
            ],
            emitted_event_names=["YokeFunctionCalled"],
            guardrails=[
                "project_scope_required",
                "item_claim_required",
                "immutable_snapshot_order",
                "actor_session_bound",
            ],
            adapter_status=(
                "live" if function_id == "qa.plan_execution.begin" else "internal"
            ),
            claim_required_kind="item",
            ambient_session_required=True,
        )
    registry.register(
        "qa.case_execution.begin",
        _case.handle_case_execution_begin,
        _case.CaseExecutionBeginRequest,
        _case.CaseExecutionBeginResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.qa_case_execution",
        target_kinds=["qa_requirement"],
        side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[
            "materialized_plan_case",
            "project_scope_required",
            "item_claim_required",
        ],
        adapter_status="live",
        claim_required_kind="item",
        ambient_session_required=True,
    )
    registry.register(
        "qa.case.rerun",
        _case.handle_case_rerun,
        _case.CaseRerunRequest,
        _case.CaseRerunResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.qa_case_execution",
        target_kinds=["qa_requirement"],
        side_effects=[
            "qa_case_execution",
            "qa_run_write",
            "qa_artifact_write",
        ],
        emitted_event_names=[
            "YokeFunctionCalled",
            "QARunStarted",
            "QARunCaptured",
            "QARunCompleted",
        ],
        guardrails=[
            "project_permission",
            "materialized_case_reread",
            "registered_executor",
        ],
        adapter_status="internal",
        claim_required_kind=None,
        ambient_session_required=False,
    )
    registry.register(
        "qa.case.waive",
        _case.handle_case_waive,
        _case.CaseWaiveRequest,
        _case.CaseWaiveResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.qa_case_execution",
        target_kinds=["qa_requirement"],
        side_effects=["qa_requirements_update"],
        emitted_event_names=["YokeFunctionCalled", "QARequirementWaived"],
        guardrails=[
            "project_permission",
            "operator_rationale",
            "materialized_requirement",
        ],
        adapter_status="internal",
        claim_required_kind=None,
        ambient_session_required=False,
    )


__all__ = ["register"]
