"""Registered handlers for session-owned project steering claims."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, ValidationError

from yoke_contracts.steering_claims import DEFAULT_STEERING_DOC_SLUG
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class SteeringClaimRow(BaseModel):
    id: int
    session_id: str
    target_kind: str
    scope: Dict[str, int]
    claim_type: str = "exclusive"
    claimed_at: str
    last_heartbeat: str
    released_at: Optional[str] = None
    release_reason: Optional[str] = None
    reason: Optional[str] = None
    reason_intent: Optional[str] = None
    release_reason_intent: Optional[str] = None
    document_claim: Optional[Dict[str, Any]] = None


class AcquireRequest(BaseModel):
    reason: Optional[str] = None
    doc_slug: str = Field(DEFAULT_STEERING_DOC_SLUG, min_length=1)


class AcquireResponse(BaseModel):
    claim: SteeringClaimRow


class ReleaseRequest(BaseModel):
    reason: str = Field(..., min_length=1)


class ReleaseResponse(BaseModel):
    claim: SteeringClaimRow


class ListRequest(BaseModel):
    session_id: Optional[str] = None
    active_only: bool = False


class ListResponse(BaseModel):
    claims: List[SteeringClaimRow] = Field(default_factory=list)


def _error(code: str, message: str, jsonpath: str = "$.payload") -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message, jsonpath=jsonpath),
    )


def _authorized_project_id(request: FunctionCallRequest) -> int | None:
    raw = (request.options or {}).get("authorized_project_id")
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def _claim_payload(row: Any) -> dict[str, Any]:
    payload = dict(row)
    payload["id"] = int(payload["id"])
    payload["scope"] = dict(payload["scope"])
    return payload


def handle_acquire(request: FunctionCallRequest) -> HandlerOutcome:
    try:
        body = AcquireRequest.model_validate(request.payload or {})
    except ValidationError as exc:
        return _error("payload_invalid", f"acquire payload invalid: {exc}")
    project_id = _authorized_project_id(request)
    if project_id is None:
        return _error(
            "project_context_required",
            "steering acquire requires --project <slug-or-id>",
            "$.target.project_id",
        )

    from yoke_core.domain import db_helpers
    from yoke_core.domain.sessions_analytics import SessionError
    from yoke_core.domain.steering_claims import acquire

    with db_helpers.connect() as conn:
        try:
            row = acquire(
                conn,
                session_id=request.actor.session_id,
                project_id=project_id,
                reason=body.reason,
                doc_slug=body.doc_slug,
                actor_id=(
                    int(request.actor.actor_id)
                    if request.actor.actor_id is not None
                    else None
                ),
            )
        except SessionError as exc:
            code = {
                "ALREADY_CLAIMED": "already_claimed",
                "DOCUMENT_ALREADY_CLAIMED": "document_already_claimed",
                "DOCUMENT_NOT_FOUND": "unknown_document",
                "DOCUMENT_MISMATCH": "document_mismatch",
            }.get(exc.code, "claim_failed")
            return _error(code, f"{exc.code}: {exc}")
    return HandlerOutcome(result_payload={"claim": _claim_payload(row)})


def handle_release(request: FunctionCallRequest) -> HandlerOutcome:
    try:
        body = ReleaseRequest.model_validate(request.payload or {})
    except ValidationError as exc:
        return _error("payload_invalid", f"release payload invalid: {exc}")
    if request.target.claim_id is None:
        return _error(
            "payload_invalid",
            "steering release requires a claim target",
            "$.target.claim_id",
        )

    from yoke_core.domain import db_helpers
    from yoke_core.domain.sessions_analytics import SessionError
    from yoke_core.domain.sessions_lifecycle_claim import release_claim
    from yoke_core.domain.strategy_execution import StrategyExecutionError

    with db_helpers.connect() as conn:
        try:
            row = release_claim(conn, int(request.target.claim_id), reason=body.reason)
        except SessionError as exc:
            return _error("release_failed", f"{exc.code}: {exc}")
        except StrategyExecutionError as exc:
            return _error(
                "paired_document_release_failed",
                f"{exc}; inspect the steering seat and document lock, then retry",
            )
    return HandlerOutcome(result_payload={"claim": _claim_payload(row)})


def handle_list(request: FunctionCallRequest) -> HandlerOutcome:
    try:
        body = ListRequest.model_validate(request.payload or {})
    except ValidationError as exc:
        return _error("payload_invalid", f"list payload invalid: {exc}")
    project_id = _authorized_project_id(request)
    if project_id is None:
        return _error(
            "project_context_required",
            "steering list requires project context",
            "$.target.project_id",
        )

    from yoke_core.domain import db_helpers
    from yoke_core.domain.steering_claims import list_claims

    with db_helpers.connect() as conn:
        rows = list_claims(
            conn,
            project_id=project_id,
            session_id=body.session_id,
            active_only=body.active_only,
        )
    return HandlerOutcome(
        result_payload={"claims": [_claim_payload(row) for row in rows]},
    )


__all__ = [
    "AcquireRequest",
    "AcquireResponse",
    "ListRequest",
    "ListResponse",
    "ReleaseRequest",
    "ReleaseResponse",
    "SteeringClaimRow",
    "handle_acquire",
    "handle_list",
    "handle_release",
]
