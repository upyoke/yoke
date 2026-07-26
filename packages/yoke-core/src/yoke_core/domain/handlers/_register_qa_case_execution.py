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


__all__ = ["register"]
