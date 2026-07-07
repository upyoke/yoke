"""Handlers for hook.* operations."""

from __future__ import annotations

from pydantic import BaseModel

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class HookEvaluateRequest(BaseModel):
    event_name: str
    dry_run: bool = False


class HookEvaluateResponse(BaseModel):
    exit_code: int


def handle_hook_evaluate(request: FunctionCallRequest) -> HandlerOutcome:
    payload = request.payload or {}
    event_name = payload.get("event_name")
    if not isinstance(event_name, str) or not event_name.strip():
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="payload_invalid",
                message="event_name is required",
                jsonpath="$.payload.event_name",
            ),
        )

    from runtime.harness.hook_runner.__main__ import main as hook_runner_main

    runner_args = [event_name.strip()]
    if bool(payload.get("dry_run", False)):
        runner_args.append("--dry-run")
    rc = int(hook_runner_main(runner_args))
    return HandlerOutcome(
        result_payload={"exit_code": rc},
        primary_success=(rc == 0),
        error=None if rc == 0 else FunctionError(
            code="hook_evaluate_failed",
            message=f"hook runner exited with {rc}",
        ),
    )


__all__ = [
    "HookEvaluateRequest",
    "HookEvaluateResponse",
    "handle_hook_evaluate",
]
