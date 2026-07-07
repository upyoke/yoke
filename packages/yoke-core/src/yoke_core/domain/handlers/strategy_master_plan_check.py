"""Handler for ``strategy.master_plan_check.run``."""

from __future__ import annotations

from typing import Any, Dict, List

from pydantic import BaseModel

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class StrategyMasterPlanCheckRequest(BaseModel):
    markdown: str


class StrategyMasterPlanCheckResponse(BaseModel):
    report: Dict[str, Any]
    markdown_report: str
    contradiction_count: int


def _bad_request(message: str, *, jsonpath: str = "$.payload") -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(
            code="payload_invalid",
            message=message,
            jsonpath=jsonpath,
        ),
    )


def handle_strategy_master_plan_check(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    try:
        payload = StrategyMasterPlanCheckRequest.model_validate(
            request.payload or {}
        )
    except Exception as exc:
        return _bad_request(f"payload invalid: {exc}")
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.master_plan_check import render_report, run_validation

    conn = connect()
    try:
        result = run_validation(payload.markdown, conn)
    finally:
        conn.close()
    report = result.to_dict()
    return HandlerOutcome(
        result_payload=StrategyMasterPlanCheckResponse(
            report=report,
            markdown_report=render_report(result),
            contradiction_count=len(result.contradictions),
        ).model_dump(),
        primary_success=True,
    )


REGISTRATIONS: List[Dict[str, Any]] = [
    {
        "function_id": "strategy.master_plan_check.run",
        "handler": handle_strategy_master_plan_check,
        "request_model": StrategyMasterPlanCheckRequest,
        "response_model": StrategyMasterPlanCheckResponse,
        "stability": "stable",
        "owner_module": "yoke_core.domain.handlers.strategy_master_plan_check",
        "target_kinds": ["global"],
        "side_effects": [],
        "emitted_event_names": ["YokeFunctionCalled"],
        "guardrails": [],
        "adapter_status": "live",
        "claim_required_kind": None,
    },
]


__all__ = [
    "REGISTRATIONS",
    "handle_strategy_master_plan_check",
]
