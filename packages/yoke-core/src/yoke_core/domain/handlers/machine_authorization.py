"""Signed-in workbench reads and personal approval of a device code."""

from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_core.domain import db_backend, db_helpers
from yoke_core.domain.machine_authorization_codes import (
    MachineAuthorizationError,
    inspect,
    resolve,
)


class AuthorizationGetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=1, max_length=32)


class AuthorizationResolveRequest(AuthorizationGetRequest):
    action: Literal["approve", "deny"]


class AuthorizationResponse(BaseModel):
    authorization: dict[str, Any]


def _handle(request: FunctionCallRequest, model: Any, operation: Any) -> HandlerOutcome:
    try:
        payload = model.model_validate(request.payload or {})
        actor = str(request.actor.actor_id or "")
        if not actor.isdigit():
            raise MachineAuthorizationError(
                "actor_required", "sign in to approve your own machine", 401
            )
        with db_helpers.connect() as conn:
            result = operation(conn, **payload.model_dump(), actor_id=int(actor))
        return HandlerOutcome(
            primary_success=True, result_payload={"authorization": result}
        )
    except MachineAuthorizationError as exc:
        return HandlerOutcome(
            primary_success=False, error=FunctionError(code=exc.code, message=str(exc))
        )
    except (ValueError, PermissionError) as exc:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="authorization_refused",
                message=f"{exc}; sign in again or start a fresh connection code",
            ),
        )
    except db_backend.database_error_types():
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="authorization_store_unavailable",
                message="ask the server operator to check database health, then retry",
            ),
        )


def handle_get(request: FunctionCallRequest) -> HandlerOutcome:
    return _handle(request, AuthorizationGetRequest, inspect)


def handle_resolve(request: FunctionCallRequest) -> HandlerOutcome:
    return _handle(request, AuthorizationResolveRequest, resolve)
