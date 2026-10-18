"""Registered universe-wide Cursor monthly quota order."""

from pydantic import BaseModel, ConfigDict, ValidationError
from yoke_contracts.api.function_call import FunctionError, HandlerOutcome
from yoke_core.domain.db_helpers import connect
from yoke_core.domain.handlers.identity_common import caller_actor_id
from yoke_core.domain.quota_pool_order import (
    QuotaPoolOrderError,
    read_pool_order,
    set_pool_order,
)
from yoke_core.domain.pydantic_validation_safety import safe_validation_message

GET_FUNCTION_ID = "universe.cursor_quota_order.get"
SET_FUNCTION_ID = "universe.cursor_quota_order.set"


class GetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pools: list[str] | None


class OrderResponse(BaseModel):
    pools: list[str]
    source: str | None = None


def _failure(code, message):
    return HandlerOutcome(
        primary_success=False, error=FunctionError(code=code, message=message)
    )


def handle_get(request):
    try:
        GetRequest.model_validate(request.payload or {})
        with connect() as conn:
            ordered = read_pool_order(conn)
            from yoke_core.domain.machine_registry import marker

            stored = conn.execute(
                f"SELECT 1 FROM universe_settings WHERE key={marker(conn)}",
                ("cursor_quota_order",),
            ).fetchone()
        return HandlerOutcome(
            result_payload={
                "pools": list(ordered),
                "source": "stored" if stored else "default",
            }
        )
    except ValidationError as exc:
        return _failure("payload_invalid", safe_validation_message(exc))
    except QuotaPoolOrderError as exc:
        return _failure(exc.code, str(exc))


def handle_set(request):
    try:
        parsed = SetRequest.model_validate(request.payload)
    except ValidationError as exc:
        return _failure("payload_invalid", safe_validation_message(exc))
    actor_id, actor_error = caller_actor_id(request)
    if actor_error is not None:
        return HandlerOutcome(primary_success=False, error=actor_error)
    try:
        with connect() as conn:
            ordered = set_pool_order(conn, pools=parsed.pools, actor_id=actor_id)
        return HandlerOutcome(result_payload={"pools": list(ordered)})
    except QuotaPoolOrderError as exc:
        return _failure(exc.code, str(exc))
