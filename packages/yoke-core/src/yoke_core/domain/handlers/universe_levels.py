"""Registered read and write for the universe execution levels."""

from __future__ import annotations

from typing import Any, Dict, List

from pydantic import BaseModel, ConfigDict, ValidationError

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_contracts.level_proposals import (
    published_capability_conflicts,
    refuse_capability_conflicts,
)
from yoke_contracts.levels import LevelsError, levels_payload, parse_levels
from yoke_contracts.model_reference_records import ModelReferenceError
from yoke_core.domain.pydantic_validation_safety import safe_validation_message

GET_FUNCTION_ID = "universe.levels.get"
SET_FUNCTION_ID = "universe.levels.set"
CAPACITY_FUNCTION_ID = "universe.level_capacity.get"


class UniverseLevelsGetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class UniverseLevelsSetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    levels: List[Dict[str, Any]]


class UniverseLevelsResponse(BaseModel):
    source: str
    levels: List[Dict[str, Any]]


class UniverseLevelsCapacityResponse(BaseModel):
    read_at: str
    source: str
    usable_machines: int
    live_workers: Dict[str, int]
    levels: List[Dict[str, Any]]
    projects: List[Dict[str, Any]]


def _failure(code: str, message: str, jsonpath: str = "$.payload") -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message, jsonpath=jsonpath),
    )


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


def handle_universe_levels_capacity_get(request: FunctionCallRequest) -> HandlerOutcome:
    """Return what each level can launch now, where the caller's next launch
    at each level goes per project, and which projects override."""
    try:
        UniverseLevelsGetRequest(**(request.payload or {}))
    except ValidationError as exc:
        return _failure("payload_invalid", safe_validation_message(exc))
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.handlers.session_launch import launch_authorization
    from yoke_core.domain.universe_level_capacity_read import read_level_capacity
    from yoke_core.domain.universe_levels import UniverseLevelsError

    try:
        with connect() as conn:
            result = read_level_capacity(
                conn,
                authorize=lambda project_id: launch_authorization(
                    conn, request, project_id
                ),
            )
    except LevelsError as exc:
        return _failure(
            exc.code,
            f"stored levels no longer validate at {exc.field}: {exc.detail} "
            "Recovery: rewrite the universe levels with `yoke universe levels "
            "set --stdin`, or the project override with `yoke projects "
            "capability-settings set --cap-type session-routing`.",
        )
    except UniverseLevelsError as exc:
        return _failure(exc.code, str(exc))
    return HandlerOutcome(result_payload=result)


def handle_universe_levels_set(request: FunctionCallRequest) -> HandlerOutcome:
    """Validate and store the universe levels, replacing the prior definition.

    An option whose effort or context window its model's published catalog
    values contradict is refused before anything is stored.
    """
    try:
        parsed = UniverseLevelsSetRequest(**(request.payload or {}))
    except ValidationError as exc:
        return _failure("payload_invalid", safe_validation_message(exc))
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.handlers.identity_common import caller_actor_id
    from yoke_core.domain.model_reference_store import revision_at
    from yoke_core.domain.universe_levels import write_universe_levels

    try:
        with connect() as conn:
            try:
                records = revision_at(conn)["records"]
            except ModelReferenceError:
                records = ()  # no catalog yet: every option is unverified
            conflicts, _ = published_capability_conflicts(
                parse_levels(parsed.levels), records
            )
            refuse_capability_conflicts(conflicts)
            levels = write_universe_levels(
                conn, parsed.levels, actor_id=caller_actor_id(conn, request)
            )
    except LevelsError as exc:
        return _failure(
            exc.code, f"{exc.field}: {exc.detail}", f"$.payload.{exc.field}"
        )
    return HandlerOutcome(
        result_payload={"source": "universe", "levels": levels_payload(levels)}
    )


__all__ = [
    "CAPACITY_FUNCTION_ID",
    "GET_FUNCTION_ID",
    "SET_FUNCTION_ID",
    "UniverseLevelsCapacityResponse",
    "UniverseLevelsGetRequest",
    "UniverseLevelsResponse",
    "UniverseLevelsSetRequest",
    "handle_universe_levels_capacity_get",
    "handle_universe_levels_get",
    "handle_universe_levels_set",
]
