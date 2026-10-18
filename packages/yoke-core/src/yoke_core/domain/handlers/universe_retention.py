"""Registered admin-only retention read and one bounded prune pass."""

from pydantic import ValidationError

from yoke_contracts.api.function_call import FunctionError, HandlerOutcome
from yoke_contracts.universe_retention import PruneRequest, RetentionReadRequest
from yoke_core.domain.pydantic_validation_safety import safe_validation_message


def handle_get(request):
    return _handle(request, False)


def handle_prune(request):
    return _handle(request, True)


def _handle(request, prune):
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.universe_retention import read_retention
    from yoke_core.domain.universe_retention_pass import prune_pass

    try:
        parsed = (PruneRequest if prune else RetentionReadRequest).model_validate(
            request.payload or {}
        )
    except ValidationError as exc:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="payload_invalid",
                message=safe_validation_message(exc),
                jsonpath="$.payload",
            ),
        )
    try:
        with connect() as conn:
            result = prune_pass(conn, parsed) if prune else read_retention(conn)[1]
    except ValueError as exc:
        code, _, message = str(exc).partition(":")
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code=code,
                message=message.strip(),
            ),
        )
    except Exception as exc:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="retention_pass_outcome_unknown"
                if prune
                else "retention_read_failed",
                message=(
                    f"The prune pass could not be acknowledged ({type(exc).__name__}); its outcome/count is unknown and any commits remain committed. Recovery: restore the database connection and rerun universe prune."
                    if prune
                    else f"The selected universe's retention/identity could not be read ({type(exc).__name__}). Recovery: restore its database connection and retry."
                ),
            ),
        )
    failure = result.get("failure")
    return HandlerOutcome(
        result_payload=result,
        primary_success=not failure,
        error=FunctionError(
            code=failure["code"],
            message=f"{failure['table']}: {failure['reason']}. {failure['recovery']}",
        )
        if failure
        else None,
    )
