"""Registered read and write for the universe execution levels."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, ValidationError

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_contracts.levels import LevelsError, levels_payload
from yoke_core.domain.pydantic_validation_safety import safe_validation_message

GET_FUNCTION_ID = "universe.levels.get"
SET_FUNCTION_ID = "universe.levels.set"


class UniverseLevelsGetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class UniverseLevelsSetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    levels: List[Dict[str, Any]]


class UniverseLevelsResponse(BaseModel):
    source: str
    levels: List[Dict[str, Any]]


def _failure(code: str, message: str, jsonpath: str = "$.payload") -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message, jsonpath=jsonpath),
    )


def _actor_id(request: FunctionCallRequest) -> Optional[int]:
    raw = str(request.actor.actor_id or "").strip()
    return int(raw) if raw.isdigit() else None


def handle_universe_levels_get(request: FunctionCallRequest) -> HandlerOutcome:
    """Return the universe levels and whether they are stored or shipped."""
    try:
        UniverseLevelsGetRequest(**(request.payload or {}))
    except ValidationError as exc:
        return _failure("payload_invalid", safe_validation_message(exc))
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.universe_levels import (
        UniverseLevelsError,
        effective_levels,
    )

    try:
        with connect() as conn:
            levels, source = effective_levels(conn, None)
    except (LevelsError, UniverseLevelsError) as exc:
        return _failure(
            getattr(exc, "code", "levels_document_invalid"),
            f"{exc}. Recovery: store a valid document with "
            "`yoke universe levels set --stdin`.",
        )
    return HandlerOutcome(
        result_payload={"source": source, "levels": levels_payload(levels)}
    )


def handle_universe_levels_set(request: FunctionCallRequest) -> HandlerOutcome:
    """Validate and store the universe levels, replacing the prior definition."""
    try:
        parsed = UniverseLevelsSetRequest(**(request.payload or {}))
    except ValidationError as exc:
        return _failure("payload_invalid", safe_validation_message(exc))
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.universe_levels import write_universe_levels

    try:
        with connect() as conn:
            levels = write_universe_levels(
                conn, parsed.levels, actor_id=_actor_id(request)
            )
    except LevelsError as exc:
        return _failure(
            exc.code, f"{exc.field}: {exc.detail}", f"$.payload.{exc.field}"
        )
    return HandlerOutcome(
        result_payload={"source": "universe", "levels": levels_payload(levels)}
    )


__all__ = [
    "GET_FUNCTION_ID",
    "SET_FUNCTION_ID",
    "UniverseLevelsGetRequest",
    "UniverseLevelsResponse",
    "UniverseLevelsSetRequest",
    "handle_universe_levels_get",
    "handle_universe_levels_set",
]
