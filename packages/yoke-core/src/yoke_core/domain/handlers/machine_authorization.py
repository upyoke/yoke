"""Signed-in workbench reads and personal approval of a device code."""

from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_core.domain import db_backend, db_helpers
from yoke_core.domain.machine_authorization_codes import (
    MachineAuthorizationError,
)
from yoke_core.domain.machine_authorization_decisions import inspect, pending, resolve


class AuthorizationPendingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AuthorizationActor(BaseModel):
    actor_id: int
    name: str


class PendingAuthorization(BaseModel):
    code: str
    machine: str
    machine_id: str
    platform: str | None
    expires_at: str
    requested_by: AuthorizationActor | None
    state: Literal["pending"]


class AuthorizationPendingResponse(BaseModel):
    viewer: AuthorizationActor
    requests: list[PendingAuthorization]
    mode: Literal["local", "self-host", "hosted"]


class AuthorizationGetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=1, max_length=32)


class AuthorizationResolveRequest(AuthorizationGetRequest):
    action: Literal["approve", "deny"]


class AuthorizationResponse(BaseModel):
    authorization: dict[str, Any]


def _handle(
    request: FunctionCallRequest,
    model: Any,
    operation: Any,
    *,
    result_key: str | None = "authorization",
) -> HandlerOutcome:
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
            primary_success=True,
            result_payload={result_key: result} if result_key else result,
        )
    except MachineAuthorizationError as exc:
        return HandlerOutcome(
            primary_success=False, error=FunctionError(code=exc.code, message=str(exc))
        )
    except ValidationError:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="authorization_refused",
                message="send the documented machine-authorization payload with valid field types and limits",
            ),
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


def handle_pending(request: FunctionCallRequest) -> HandlerOutcome:
    return _handle(request, AuthorizationPendingRequest, pending, result_key=None)
