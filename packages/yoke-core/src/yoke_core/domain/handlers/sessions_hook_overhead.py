"""Registered ``sessions.hook_overhead`` read handler."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class SessionsHookOverheadRequest(BaseModel):
    hours: int = 24


class SessionsHookOverheadResponse(BaseModel):
    fields: list[str]
    rows: list[dict[str, Any]]


def _error(message: str, *, jsonpath: str) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code="payload_invalid", message=message, jsonpath=jsonpath),
    )


def handle_sessions_hook_overhead(request: FunctionCallRequest) -> HandlerOutcome:
    if request.target.kind != "global":
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="target_invalid",
                message="sessions.hook_overhead requires target.kind='global'",
                jsonpath="$.target.kind",
            ),
        )
    hours = (request.payload or {}).get("hours", 24)
    if isinstance(hours, bool) or not isinstance(hours, int):
        return _error("hours must be an integer", jsonpath="$.payload.hours")
    if not 1 <= hours <= 720:
        return _error("hours must be between 1 and 720", jsonpath="$.payload.hours")

    from yoke_core.domain.hook_overhead import (
        HOOK_OVERHEAD_FIELDS,
        hook_overhead_rows,
    )

    return HandlerOutcome(
        result_payload={
            "fields": HOOK_OVERHEAD_FIELDS,
            "rows": hook_overhead_rows(hours),
        },
        primary_success=True,
    )


__all__ = [
    "SessionsHookOverheadRequest",
    "SessionsHookOverheadResponse",
    "handle_sessions_hook_overhead",
]
