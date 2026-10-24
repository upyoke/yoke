"""Registered read and write for the universe execution levels."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

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
from yoke_contracts.levels import (
    LevelsError,
    default_levels,
    levels_payload,
    parse_levels,
)
from yoke_contracts.model_reference_records import ModelReferenceError
from yoke_contracts.refusal_recovery import compose_refusal

from yoke_core.domain.pydantic_validation_safety import safe_validation_message

GET_FUNCTION_ID = "universe.levels.get"
SET_FUNCTION_ID = "universe.levels.set"
RESET_FUNCTION_ID = "universe.levels.reset"
CAPACITY_FUNCTION_ID = "universe.level_capacity.get"


class UniverseLevelsGetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class UniverseLevelsSetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    levels: List[Dict[str, Any]]


class UniverseLevelsResponse(BaseModel):
    source: str
    levels: List[Dict[str, Any]]
    # Set only when ``source`` is ``universe``: whether the stored document
    # differs from the defaults this release ships.
    shipped_defaults_differ: Optional[bool] = None


class UniverseLevelsResetResponse(UniverseLevelsResponse):
    cleared: bool


class UniverseLevelsCapacityResponse(BaseModel):
    cursor_quota_order: List[str]
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
        shipped_defaults_differ,
    )

    try:
        with connect() as conn:
            levels, source = effective_levels(conn, None)
            differ = shipped_defaults_differ(conn)
    except (LevelsError, UniverseLevelsError) as exc:
        return _failure(
            getattr(exc, "code", "levels_document_invalid"),
            compose_refusal(
                f"{exc}.",
                recovery=(
                    "store a valid document with `yoke settings set levels -`, or follow "
                    "shipped defaults with `yoke settings unset levels`."
                ),
            ),
        )
    result: Dict[str, Any] = {"source": source, "levels": levels_payload(levels)}
    if source == "universe":
        result["shipped_defaults_differ"] = differ
    return HandlerOutcome(result_payload=result)


def handle_universe_levels_reset(request: FunctionCallRequest) -> HandlerOutcome:
    """Delete the stored universe levels so the universe follows shipped defaults."""
    try:
        UniverseLevelsGetRequest(**(request.payload or {}))
    except ValidationError as exc:
        return _failure("payload_invalid", safe_validation_message(exc))
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.universe_levels import clear_universe_levels

    with connect() as conn:
        cleared = clear_universe_levels(conn)
    return HandlerOutcome(
        result_payload={
            "source": "default",
            "levels": levels_payload(default_levels()),
            "cleared": cleared,
        }
    )


def handle_universe_levels_capacity_get(request: FunctionCallRequest) -> HandlerOutcome:
    """Return current model-row capacity and Cursor monthly pool order."""
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
            compose_refusal(
                f"stored levels no longer validate at {exc.field}: {exc.detail}",
                recovery=(
                    "rewrite the universe levels with `yoke settings set levels --stdin`, or "
                    "the project override with `yoke projects capability-settings set "
                    "--cap-type session-routing`."
                ),
            ),
        )
    except UniverseLevelsError as exc:
        return _failure(exc.code, str(exc))
    return HandlerOutcome(result_payload=result)


def handle_universe_levels_set(request: FunctionCallRequest) -> HandlerOutcome:
    """Validate and store the universe levels, replacing the prior definition.

    A document equal to the shipped defaults stores nothing (source
    ``default``), so the universe keeps following shipped defaults.
    A minimum effort that its model's published catalog values contradict is refused before anything is stored.
    """
    try:
        parsed = UniverseLevelsSetRequest(**(request.payload or {}))
    except ValidationError as exc:
        return _failure("payload_invalid", safe_validation_message(exc))
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.handlers.identity_common import caller_actor_id
    from yoke_core.domain.model_reference_store import revision_at
    from yoke_core.domain.universe_levels import write_universe_levels

    caller_id, caller_error = caller_actor_id(request)
    if caller_error is not None:
        return HandlerOutcome(primary_success=False, error=caller_error)
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
            levels, source = write_universe_levels(
                conn, parsed.levels, actor_id=caller_id
            )
    except LevelsError as exc:
        return _failure(
            exc.code, f"{exc.field}: {exc.detail}", f"$.payload.{exc.field}"
        )
    result: Dict[str, Any] = {"source": source, "levels": levels_payload(levels)}
    if source == "universe":
        result["shipped_defaults_differ"] = True
    return HandlerOutcome(result_payload=result)


__all__ = [
    "CAPACITY_FUNCTION_ID",
    "GET_FUNCTION_ID",
    "RESET_FUNCTION_ID",
    "SET_FUNCTION_ID",
    "UniverseLevelsCapacityResponse",
    "UniverseLevelsGetRequest",
    "UniverseLevelsResetResponse",
    "UniverseLevelsResponse",
    "UniverseLevelsSetRequest",
    "handle_universe_levels_capacity_get",
    "handle_universe_levels_get",
    "handle_universe_levels_reset",
    "handle_universe_levels_set",
]
