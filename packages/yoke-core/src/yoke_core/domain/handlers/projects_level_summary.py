"""The registered read behind a project's execution levels.

A project reads its ``session-routing`` override when it carries one and the
universe levels otherwise. This read answers which, and returns the levels
themselves — glyph and ordered options per level, lowest first — so every
surface shows what labeling and launch will actually use.
"""

from __future__ import annotations

from typing import Any, Dict, List

from pydantic import BaseModel, ConfigDict, ValidationError

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_contracts.levels import LevelsError, levels_payload
from yoke_core.domain.pydantic_validation_safety import safe_validation_message


class LevelSummaryGetRequest(BaseModel):
    """Select one project's effective execution levels."""

    model_config = ConfigDict(extra="forbid")

    project: str


class LevelSummaryResponse(BaseModel):
    project: str
    project_id: int
    source: str
    configured: bool
    levels: List[Dict[str, Any]]


def _authorized_project_ref(request: FunctionCallRequest, payload_project: str) -> str:
    """Prefer the concrete project identity resolved by authorization."""
    authorized = (request.options or {}).get("authorized_project_id")
    if authorized is None:
        return payload_project
    return str(int(authorized))


def handle_level_summary_get(request: FunctionCallRequest) -> HandlerOutcome:
    """Return the project's effective levels and where they come from."""
    try:
        parsed = LevelSummaryGetRequest(**(request.payload or {}))
    except ValidationError as exc:
        return _failure("payload_invalid", safe_validation_message(exc), "$.payload")

    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.project_identity import resolve_project_id
    from yoke_core.domain.universe_levels import UniverseLevelsError, effective_levels

    project_ref = _authorized_project_ref(request, parsed.project)
    try:
        with connect() as conn:
            project_id = resolve_project_id(conn, project_ref)
            levels, source = effective_levels(conn, project_id)
    except LookupError as exc:
        return _failure("not_found", str(exc), "$.payload.project")
    except LevelsError as exc:
        return _failure(
            exc.code,
            f"the stored levels no longer validate at {exc.field}: {exc.detail} "
            "Recovery: rewrite the project override with `yoke projects "
            "capability-settings set --cap-type session-routing`, or the "
            "universe levels with `yoke universe levels set --stdin`.",
            "$.payload.project",
        )
    except (UniverseLevelsError, ValueError) as exc:
        return _failure(getattr(exc, "code", "validation_error"), str(exc), "$.payload")
    return HandlerOutcome(
        result_payload={
            "project": parsed.project,
            "project_id": project_id,
            "source": source,
            "configured": source == "project",
            "levels": levels_payload(levels),
        }
    )


def _failure(code: str, message: str, jsonpath: str) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message, jsonpath=jsonpath),
    )


__all__ = [
    "LevelSummaryGetRequest",
    "LevelSummaryResponse",
    "handle_level_summary_get",
]
