"""Ordered batch endpoint for resident read-only hook observations."""

from __future__ import annotations

import json
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.routing import APIRouter
from pydantic import BaseModel, Field, ValidationError

from yoke_contracts.hook_evaluator_protocol import (
    HOOK_BATCH_MODEL_CONFIRMATIONS_FIELD,
)
from yoke_contracts.hook_resident_routing import is_read_only_tool_event
from yoke_core.api.http_auth import require_auth_context
from yoke_core.domain.session_ambient_identity import (
    is_conversation_shaped_session_id,
)
from yoke_core.hooks.observation_batch import persist_observation_batch


router = APIRouter()
_BATCH_LIMIT = 64


class HookObservation(BaseModel):
    observation_id: str = Field(min_length=1, max_length=128)
    observed_at: str = Field(min_length=1, max_length=64)
    hook_wait_ms: int = Field(ge=0, le=600_000)
    hook_request: dict[str, Any]


class HookObservationBatchRequest(BaseModel):
    hook_schema: int = 1
    observations: list[HookObservation] = Field(min_length=1, max_length=_BATCH_LIMIT)


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message}},
    )


@router.post("/hooks/telemetry/batch")
def post_hook_observation_batch(
    http_request: Request,
    batch: HookObservationBatchRequest,
) -> JSONResponse:
    """Persist one idempotent prefix; non-2xx makes the resident retry it."""
    if batch.hook_schema != 1:
        return _error(
            400,
            "UNSUPPORTED_HOOK_OBSERVATION_SCHEMA",
            f"hook_schema {batch.hook_schema} is not supported",
        )
    auth = require_auth_context(http_request)
    from yoke_core.api.routes.hooks import HookEvaluateRequest, HOOK_WIRE_SCHEMA

    validated: list[dict[str, Any]] = []
    project_ids: set[int] = set()
    for observation in batch.observations:
        try:
            hook_request = HookEvaluateRequest.model_validate(observation.hook_request)
        except ValidationError as exc:
            return _error(
                400,
                "HOOK_OBSERVATION_REQUEST_INVALID",
                f"batched hook request is invalid ({exc.error_count()} field errors)",
            )
        if hook_request.hook_schema != HOOK_WIRE_SCHEMA:
            return _error(
                400,
                "UNSUPPORTED_HOOK_SCHEMA",
                f"hook_schema {hook_request.hook_schema} is not supported",
            )
        if not is_read_only_tool_event(hook_request.event_name, hook_request.stdin):
            return _error(
                400,
                "HOOK_OBSERVATION_NOT_READ_ONLY",
                "only canonical read-only tool chains may use telemetry batching",
            )
        try:
            payload = json.loads(hook_request.stdin or "{}")
        except (TypeError, ValueError):
            payload = {}
        if not isinstance(payload, dict) or payload.get("identity_stamped") is not True:
            return _error(
                400,
                "HOOK_OBSERVATION_IDENTITY_REQUIRED",
                "batched hook payload is not identity-stamped",
            )
        session_id = payload.get("session_id")
        if not isinstance(session_id, str) or is_conversation_shaped_session_id(
            payload, session_id=session_id
        ):
            return _error(
                400,
                "HOOK_OBSERVATION_SESSION_INVALID",
                "batched hook payload has no canonical session id",
            )
        if hook_request.project_id is None:
            return _error(
                403,
                "HOOK_OBSERVATION_PROJECT_REQUIRED",
                "batched hook payload has no project id",
            )
        project_ids.add(int(hook_request.project_id))
        raw = observation.model_dump()
        raw["hook_request"] = hook_request.model_dump()
        validated.append(raw)

    try:
        from yoke_core.domain import db_helpers
        from yoke_core.domain.actor_project_visibility import actor_visible_project_ids

        with db_helpers.connect() as conn:
            visible = actor_visible_project_ids(conn, auth.actor_id) or set()
    except Exception:
        return _error(
            503,
            "HOOK_OBSERVATION_AUTH_UNAVAILABLE",
            "project authorization could not be checked; retry the batch",
        )
    if not project_ids.issubset({int(value) for value in visible}):
        return _error(
            403,
            "HOOK_OBSERVATION_PROJECT_DENIED",
            "actor cannot access every project in the observation batch",
        )
    try:
        accepted, model_confirmations = persist_observation_batch(
            validated, actor_id=auth.actor_id
        )
    except Exception as exc:
        return _error(
            503,
            "YOKE_HOOK_OBSERVATION_BATCH_FAILED",
            f"observation batch was retained for retry ({type(exc).__name__})",
        )
    response: dict[str, Any] = {"hook_schema": 1, "accepted": accepted}
    if model_confirmations:
        response[HOOK_BATCH_MODEL_CONFIRMATIONS_FIELD] = model_confirmations
    return JSONResponse(content=response)


__all__ = ["router"]
