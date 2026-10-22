"""Function registry leaf for shared QA plan-case execution."""

from __future__ import annotations

from yoke_core.domain.handlers import qa_case_execution as _case
from yoke_core.domain.handlers import qa_plan_execution as _plan
from yoke_core.domain.handlers import qa_plan_review as _review
from yoke_core.domain.handlers.qa_plan_execution_models import (
    PlanExecutionCheckinResponse,
    PlanExecutionBeginResponse,
)


def register(registry) -> None:
    from yoke_core.domain.handlers.qa_plan_execution_adoption import (
        register as register_adoption,
    )

    register_adoption(registry)
    from yoke_core.domain.handlers.qa_plan_execution_reconcile import (
        register as register_reconcile,
    )

    register_reconcile(registry)
    from yoke_core.domain.handlers.qa_plan_execution_reentry import (
        PlanExecutionPauseRequest,
        PlanExecutionResumeRequest,
        handle_execution_reentry,
    )

    for function_id, model, response in (
        (
            "qa.plan_execution.pause",
            PlanExecutionPauseRequest,
            PlanExecutionCheckinResponse,
        ),
        (
            "qa.plan_execution.resume",
            PlanExecutionResumeRequest,
            _plan.PlanExecutionStateResponse,
        ),
    ):
        registry.register(
            function_id,
            handle_execution_reentry,
            model,
            response,
            stability="stable",
            owner_module="yoke_core.domain.handlers.qa_plan_execution_reentry",
            target_kinds=["item", "global"],
            minimum_serving_version="next-release",
            side_effects=["qa_plan_execution_write"],
            emitted_event_names=["YokeFunctionCalled"],
            guardrails=[
                "qa_subject_authority",
                "actor_session_bound",
                "immutable_snapshot_order",
            ],
            adapter_status="internal",
            claim_required_kind="qa_subject",
            ambient_session_required=True,
        )
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
            (
                PlanExecutionCheckinResponse
                if function_id == "qa.plan_execution.heartbeat"
                else PlanExecutionBeginResponse
                if function_id == "qa.plan_execution.begin"
                else _plan.PlanExecutionStateResponse
            ),
            stability="stable",
            owner_module="yoke_core.domain.handlers.qa_plan_execution",
            target_kinds=(
                ["item", "deployment_run", "global"]
                if function_id == "qa.plan_execution.begin"
                else ["item", "global"]
            ),
            minimum_serving_version="next-release",
            side_effects=[
                "qa_plan_execution_write",
                "coordination_claim_heartbeat_or_release",
            ],
            emitted_event_names=["YokeFunctionCalled"],
            guardrails=[
                "project_scope_required",
                "qa_subject_authority",
                "immutable_snapshot_order",
                "actor_session_bound",
            ],
            adapter_status=(
                "live"
                if function_id in {"qa.plan_execution.begin", "qa.plan_execution.abort"}
                else "internal"
            ),
            claim_required_kind="qa_subject",
            ambient_session_required=True,
        )
    for function_id, handler, request_model, response_model in (
        (
            "qa.plan_review.begin",
            _review.handle_plan_review_begin,
            _review.PlanReviewBeginRequest,
            _review.PlanReviewBeginResponse,
        ),
        (
            "qa.plan_review.submit",
            _review.handle_plan_review_submit,
            _review.PlanReviewSubmitRequest,
            _review.PlanReviewSubmitResponse,
        ),
    ):
        registry.register(
            function_id,
            handler,
            request_model,
            response_model,
            stability="stable",
            owner_module="yoke_core.domain.handlers.qa_plan_review",
            target_kinds=["item", "global"],
            minimum_serving_version="next-release",
            side_effects=[
                "qa_plan_review_write",
                "qa_run_write",
                "decision_request_write_if_undetermined",
            ],
            emitted_event_names=[
                "YokeFunctionCalled",
                "QARunCompleted",
                "DecisionRequestCreated",
            ],
            guardrails=[
                "project_scope_required",
                "immutable_review_bundle",
                "complete_verdict_batch",
                "actor_session_bound",
            ],
            adapter_status="live",
            claim_required_kind="qa_subject",
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
        minimum_serving_version="next-release",
        side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[
            "materialized_plan_case",
            "project_scope_required",
            "item_claim_required",
        ],
        adapter_status="live",
        claim_required_kind="qa_subject",
        ambient_session_required=True,
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
