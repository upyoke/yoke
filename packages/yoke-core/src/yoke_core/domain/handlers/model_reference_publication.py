"""Registered catalog review and publication operations."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, ValidationError

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_contracts.model_reference_records import ModelReferenceError
from yoke_core.domain.model_reference_store import (
    preview_catalog,
    publish_catalog,
    revision_get,
    revisions_list,
)

DIFF_FUNCTION_ID = "models.diff.run"
PUBLISH_FUNCTION_ID = "models.publish.run"
REVISIONS_FUNCTION_ID = "models.revisions.list"
RESTORE_FUNCTION_ID = "models.restore.run"


class ModelsDiffRequest(BaseModel):
    catalog: list[dict[str, Any]]


class ModelsPublishRequest(ModelsDiffRequest):
    expected_base_revision_id: str = Field(..., min_length=1)
    source_note: str = Field(..., min_length=1)
    effective_at: str | None = None


class ModelsRestoreRequest(BaseModel):
    source_revision_id: str = Field(..., min_length=1)
    expected_base_revision_id: str = Field(..., min_length=1)
    source_note: str = Field(..., min_length=1)
    effective_at: str | None = None


class ModelsRevisionsRequest(BaseModel):
    pass


class ModelsDiffResponse(BaseModel):
    base_revision_id: str
    count: int
    diff: dict[str, Any]


class ModelsPublishResponse(BaseModel):
    revision_id: str
    effective_at: str
    published_at: str
    count: int
    diff: dict[str, Any]


class ModelsRevisionsResponse(BaseModel):
    revisions: list[dict[str, Any]]
    count: int


def _failure(code: str, message: str, recovery: str) -> HandlerOutcome:
    return HandlerOutcome(
        result_payload={},
        primary_success=False,
        error=FunctionError(code=code, message=message, recovery_hint=recovery),
    )


def _parse(model: type[BaseModel], request: FunctionCallRequest):
    try:
        return model.model_validate(request.payload or {})
    except ValidationError as exc:
        return _failure(
            "payload_invalid", str(exc), "Read the matching `yoke models` command help"
        )


def _actor_id(request: FunctionCallRequest) -> int | HandlerOutcome:
    raw = str(request.actor.actor_id or "").strip()
    if not raw.isdigit():
        return _failure(
            "actor_required",
            "A verified actor is required to publish models",
            "Run from an authenticated operator session",
        )
    return int(raw)


def _catalog_failure(exc: ModelReferenceError) -> HandlerOutcome:
    return _failure(
        exc.code,
        str(exc),
        "Fix the candidate, inspect `yoke models diff --stdin`, and retry",
    )


def handle_models_diff(request: FunctionCallRequest) -> HandlerOutcome:
    payload = _parse(ModelsDiffRequest, request)
    if isinstance(payload, HandlerOutcome):
        return payload
    from yoke_core.domain.db_helpers import connect

    with connect() as conn:
        try:
            result = preview_catalog(conn, payload.catalog)
        except ModelReferenceError as exc:
            return _catalog_failure(exc)
    return HandlerOutcome(result_payload=result, primary_success=True)


def handle_models_publish(request: FunctionCallRequest) -> HandlerOutcome:
    payload = _parse(ModelsPublishRequest, request)
    if isinstance(payload, HandlerOutcome):
        return payload
    actor_id = _actor_id(request)
    if isinstance(actor_id, HandlerOutcome):
        return actor_id
    from yoke_core.domain.db_helpers import connect

    with connect() as conn:
        try:
            result = publish_catalog(
                conn,
                payload.catalog,
                effective_at=payload.effective_at,
                actor_id=actor_id,
                source_note=payload.source_note,
                expected_base_revision_id=payload.expected_base_revision_id,
            )
        except ModelReferenceError as exc:
            conn.rollback()
            return _catalog_failure(exc)
    return HandlerOutcome(result_payload=result, primary_success=True)


def handle_models_restore(request: FunctionCallRequest) -> HandlerOutcome:
    payload = _parse(ModelsRestoreRequest, request)
    if isinstance(payload, HandlerOutcome):
        return payload
    actor_id = _actor_id(request)
    if isinstance(actor_id, HandlerOutcome):
        return actor_id
    from yoke_core.domain.db_helpers import connect

    with connect() as conn:
        try:
            source = revision_get(conn, payload.source_revision_id)
            result = publish_catalog(
                conn,
                [record.to_dict() for record in source["records"]],
                effective_at=payload.effective_at,
                actor_id=actor_id,
                source_note=payload.source_note,
                expected_base_revision_id=payload.expected_base_revision_id,
                source_revision_id=payload.source_revision_id,
            )
        except ModelReferenceError as exc:
            conn.rollback()
            return _catalog_failure(exc)
    return HandlerOutcome(result_payload=result, primary_success=True)


def handle_models_revisions(request: FunctionCallRequest) -> HandlerOutcome:
    payload = _parse(ModelsRevisionsRequest, request)
    if isinstance(payload, HandlerOutcome):
        return payload
    from yoke_core.domain.db_helpers import connect

    with connect() as conn:
        revisions = revisions_list(conn)
    return HandlerOutcome(
        result_payload={"revisions": revisions, "count": len(revisions)},
        primary_success=True,
    )


__all__ = [
    "DIFF_FUNCTION_ID",
    "PUBLISH_FUNCTION_ID",
    "REVISIONS_FUNCTION_ID",
    "RESTORE_FUNCTION_ID",
    "ModelsDiffRequest",
    "ModelsDiffResponse",
    "ModelsPublishRequest",
    "ModelsPublishResponse",
    "ModelsRestoreRequest",
    "ModelsRevisionsRequest",
    "ModelsRevisionsResponse",
    "handle_models_diff",
    "handle_models_publish",
    "handle_models_restore",
    "handle_models_revisions",
]
