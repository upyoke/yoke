"""Function registry leaf for shared QA plan-case execution."""

from __future__ import annotations

from yoke_core.domain.handlers import qa_case_execution as _case


def register(registry) -> None:
    registry.register(
        "qa.case_execution.get",
        _case.handle_case_execution_get,
        _case.CaseExecutionGetRequest,
        _case.CaseExecutionGetResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.qa_case_execution",
        target_kinds=["qa_requirement"],
        side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=["materialized_plan_case", "project_scope_required"],
        adapter_status="live",
        claim_required_kind=None,
        ambient_session_required=False,
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
