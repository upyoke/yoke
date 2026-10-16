"""Repeat a deployment-run create that timed out, once, under its own key."""

from __future__ import annotations

import sys
from typing import Any, Callable, Dict

from yoke_cli.transport.dispatcher import call_dispatcher
from yoke_cli.transport.https_relay_outcome import is_response_timeout
from yoke_cli.transport.response_limits import (
    DEPLOYMENT_RUN_CREATE_TIMEOUT_SECONDS,
)
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallResponse,
    FunctionWarning,
    TargetRef,
)

FUNCTION_ID = "deployment_runs.create"

REPEAT_NOTE = (
    "note: the create response timed out; repeating once with the same "
    "idempotency key, which returns the run if the server already committed it"
)
_RECOVERED_DETAIL = (
    "the first create timed out after the server committed the run; the "
    "repeat with the same idempotency key returned that run"
)
_CREATED_DETAIL = (
    "the first create timed out before the server committed a run; the "
    "repeat with the same idempotency key created it"
)
_STILL_TIMED_OUT_DETAIL = (
    "repeated once with the same idempotency key and it timed out again; "
    "re-run the identical command (same --idempotency-key) once the server "
    "settles to get the committed run back instead of a second one"
)


def _repeat_after_response_timeout(
    response: FunctionCallResponse,
    actor: ActorContext,
    *,
    target: TargetRef,
    payload: Dict[str, Any],
) -> FunctionCallResponse:
    if not is_response_timeout(response):
        return response
    print(REPEAT_NOTE, file=sys.stderr)
    repeated = call_dispatcher(
        function_id=FUNCTION_ID,
        target=target,
        payload=payload,
        actor=actor,
        timeout_s=DEPLOYMENT_RUN_CREATE_TIMEOUT_SECONDS,
    )
    if repeated.success:
        replayed = bool((repeated.result or {}).get("replayed"))
        warning = FunctionWarning(
            code="deployment_run_create_timeout_recovered",
            step="idempotent_repeat",
            detail=_RECOVERED_DETAIL if replayed else _CREATED_DETAIL,
        )
        return repeated.model_copy(update={"warnings": [*repeated.warnings, warning]})
    if is_response_timeout(repeated) and repeated.error is not None:
        error = repeated.error.model_copy(
            update={"message": f"{repeated.error.message}; {_STILL_TIMED_OUT_DETAIL}"}
        )
        return repeated.model_copy(update={"error": error})
    return repeated


def build_timeout_repeat(
    target: TargetRef,
    payload: Dict[str, Any],
) -> Callable[[FunctionCallResponse, ActorContext], FunctionCallResponse]:
    """Bind one create request to its repeat-after-timeout recovery."""
    return lambda response, actor: _repeat_after_response_timeout(
        response,
        actor,
        target=target,
        payload=payload,
    )


__all__ = ["REPEAT_NOTE", "build_timeout_repeat"]
