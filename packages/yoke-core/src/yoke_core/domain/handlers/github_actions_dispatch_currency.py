"""Answer whether a deploy stage dispatch is still that stage's newest intent.

GitHub can hold a dispatched run queued indefinitely and refuse to cancel it.
The deploy driver then replaces it with a ``--fresh`` dispatch under the same
``deploy:<project>:<run>:<stage>`` scope. Nothing stops the stuck run from
starting later, so a release workflow asks this before its first irreversible
act and exits when a newer intent has replaced it. The durable intent table
owns these facts; telemetry is never consulted.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_contracts.github_app_installation_permissions import (
    GITHUB_ACTIONS_READ_PERMISSION_LEVELS,
)
from yoke_core.domain.github_workflow_dispatch_intents import (
    DispatchIntentStoreError,
    deploy_stage_scope,
    intent_by_correlation,
    newest_scope_intent,
)
from yoke_core.domain.handlers.github_actions_set import _validate_and_resolve_auth

FUNCTION_ID = "github_actions.dispatch_intent.current"


class DispatchCurrencyRequest(BaseModel):
    project: str = Field(..., min_length=1)
    correlation_id: str = Field(..., min_length=1)


class DispatchCurrencyResponse(BaseModel):
    found: bool
    #: True only when no newer unrejected intent shares the stage scope.
    current: bool = False
    scope: str = ""
    newest_correlation_id: str = ""
    newest_run_id: str = ""


def _refusal(code: str, message: str, hint: str) -> HandlerOutcome:
    return HandlerOutcome(
        result_payload={},
        primary_success=False,
        error=FunctionError(code=code, message=message, recovery_hint=hint),
    )


def handle_dispatch_currency_get(request: FunctionCallRequest) -> HandlerOutcome:
    payload, _resolved, error = _validate_and_resolve_auth(
        request,
        DispatchCurrencyRequest,
        FUNCTION_ID,
        required_permissions=GITHUB_ACTIONS_READ_PERMISSION_LEVELS,
    )
    if error is not None:
        return error
    unavailable = (
        "workflow_dispatch_state_unavailable",
        "Restore the control-plane intent read, then retry the same correlation id.",
    )
    try:
        intent = intent_by_correlation(payload.correlation_id)
    except DispatchIntentStoreError as exc:
        return _refusal(unavailable[0], str(exc), unavailable[1])
    scope_id = request.options.get("authorized_project_id")
    if scope_id is None or (
        intent and intent.authorization_scope != f"project:{int(scope_id)}"
    ):
        return _refusal(
            "workflow_dispatch_scope_mismatch",
            "The dispatch intent is outside this authorized project scope.",
            "Read with the project that owns the dispatch request.",
        )
    if intent is None:
        return HandlerOutcome(
            result_payload=DispatchCurrencyResponse(found=False).model_dump(),
            primary_success=True,
        )
    scope = deploy_stage_scope(intent.request_id)
    if not scope:
        return _refusal(
            "workflow_dispatch_not_deploy_stage",
            f"Dispatch request {intent.request_id!r} is not a deploy stage dispatch.",
            "Ask only for a correlation id a deployment run stage dispatched.",
        )
    try:
        newest = newest_scope_intent(scope)
    except DispatchIntentStoreError as exc:
        return _refusal(unavailable[0], str(exc), unavailable[1])
    result = DispatchCurrencyResponse(found=True, scope=scope)
    if newest is not None:
        result.current = newest.correlation_id == intent.correlation_id
        result.newest_correlation_id = newest.correlation_id
        result.newest_run_id = newest.workflow_run_id
    return HandlerOutcome(result_payload=result.model_dump(), primary_success=True)


REGISTRATIONS = [
    {
        "function_id": FUNCTION_ID,
        "handler": handle_dispatch_currency_get,
        "request_model": DispatchCurrencyRequest,
        "response_model": DispatchCurrencyResponse,
        "stability": "stable",
        "owner_module": __name__,
        "target_kinds": ["global"],
        "side_effects": [],
        "emitted_event_names": [],
        "guardrails": ["project_auth_required", "dispatch_project_scope"],
        "adapter_status": "live",
        "claim_required_kind": None,
        "ambient_session_required": False,
        "minimum_serving_version": "next-release",
    }
]
