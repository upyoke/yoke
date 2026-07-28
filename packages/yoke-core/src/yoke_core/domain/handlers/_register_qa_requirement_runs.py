"""Handler registrations for QA requirement and run operations."""

from __future__ import annotations

from yoke_core.domain.handlers import (
    qa as _qa,
    qa_browser as _qa_browser,
    qa_browser_writes as _qa_browser_writes,
    qa_requirement_waive as _qa_requirement_waive,
    qa_run as _qa_run,
)


def register(registry) -> None:
    """Register QA requirement and run handlers."""
    registry.register(
        "qa.requirement.update",
        _qa.handle_qa_requirement_update,
        _qa.QaRequirementUpdateRequest,
        _qa.QaRequirementUpdateResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.qa",
        target_kinds=["qa_requirement"],
        side_effects=["qa_runs_update"],
        emitted_event_names=["YokeFunctionCalled", "QARequirementUpdated"],
        guardrails=["claim_required"],
        adapter_status="live",
        claim_required_kind="qa_subject",
    )
    registry.register(
        "qa.requirement.waive",
        _qa_requirement_waive.handle_qa_requirement_waive,
        _qa_requirement_waive.QaRequirementWaiveRequest,
        _qa_requirement_waive.QaRequirementWaiveResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.qa_requirement_waive",
        target_kinds=["qa_requirement"],
        side_effects=["qa_requirements_update"],
        emitted_event_names=["YokeFunctionCalled", "QARequirementWaived"],
        guardrails=["claim_required", "force_required_for_blocking"],
        adapter_status="live",
        claim_required_kind="qa_subject",
    )
    registry.register(
        "qa.run.record_verdict",
        _qa_run.handle_qa_run_record_verdict,
        _qa_run.QaRunRecordVerdictRequest,
        _qa_run.QaRunRecordVerdictResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.qa_run",
        target_kinds=["qa_requirement"],
        side_effects=["qa_runs_insert"],
        emitted_event_names=["YokeFunctionCalled", "QARunCompleted"],
        guardrails=["claim_required"],
        adapter_status="live",
        claim_required_kind="qa_subject",
    )
    registry.register(
        "qa.browser_context.get",
        _qa_browser.handle_qa_browser_context_get,
        _qa_browser.QaBrowserContextGetRequest,
        _qa_browser.QaBrowserContextGetResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.qa_browser",
        target_kinds=["item"],
        side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[],
        adapter_status="live",
        claim_required_kind=None,
        ambient_session_required=False,
    )
    registry.register(
        "qa.run.add",
        _qa_browser_writes.handle_qa_run_add,
        _qa_browser_writes.QaRunAddRequest,
        _qa_browser_writes.QaRunAddResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.qa_browser_writes",
        target_kinds=["qa_requirement"],
        side_effects=["qa_runs_insert"],
        emitted_event_names=[
            "YokeFunctionCalled",
            "QARunStarted",
            "QARunCaptured",
            "QARunCompleted",
        ],
        guardrails=["claim_required"],
        adapter_status="live",
        claim_required_kind="qa_subject",
    )
    registry.register(
        "qa.run.complete",
        _qa_browser_writes.handle_qa_run_complete,
        _qa_browser_writes.QaRunCompleteRequest,
        _qa_browser_writes.QaRunCompleteResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.qa_browser_writes",
        target_kinds=["qa_requirement"],
        side_effects=["qa_runs_update"],
        emitted_event_names=[
            "YokeFunctionCalled",
            "QARunCaptured",
            "QARunCompleted",
        ],
        guardrails=["claim_required"],
        adapter_status="live",
        claim_required_kind="qa_subject",
    )


__all__ = ["register"]
