"""Request parsing and subject selection for Test Mac plan cases."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ValidationError

from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome
from yoke_core.domain.handlers.test_machine import _failure


def target_plan_subject(
    request: FunctionCallRequest,
    function_id: str,
) -> tuple[int | None, str | None] | HandlerOutcome:
    if request.target.kind == "item" and request.target.item_id is not None:
        return int(request.target.item_id), None
    if request.target.kind == "deployment_run" and request.target.deployment_run_id:
        return None, str(request.target.deployment_run_id)
    return _failure(
        "target_invalid",
        f"{function_id} requires an item or deployment-run target",
    )


def parse_plan_case_request(
    model: type[BaseModel],
    payload: Any,
) -> BaseModel | HandlerOutcome:
    try:
        return model.model_validate(payload or {})
    except ValidationError as exc:
        return _failure("payload_invalid", str(exc))


__all__ = ["parse_plan_case_request", "target_plan_subject"]
