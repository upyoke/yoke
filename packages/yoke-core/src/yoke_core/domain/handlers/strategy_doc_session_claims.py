"""Registered surfaces for session-owned strategy-document locks."""

from __future__ import annotations

from typing import Any, Optional

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_core.domain import events as _events
from yoke_core.domain.handlers.strategy_doc_surface_models import (
    StrategyDocClaimAcquireRequest,
    StrategyDocClaimListRequest,
    StrategyDocClaimListResponse,
    StrategyDocClaimReleaseRequest,
    StrategyDocClaimResponse,
)
from yoke_core.domain.handlers.strategy_doc_surfaces import (
    _actor_id,
    _error,
    _model,
    _project,
    _session_id,
)
from yoke_core.domain.strategy_docs import StrategyDocMissingError
from yoke_core.domain.strategy_execution import (
    StrategyDocClaimAuthorizationError,
    StrategyDocClaimConflictError,
    StrategyExecutionError,
    acquire_session_doc_claim,
    list_strategy_doc_claims,
    release_session_doc_claim,
)
from yoke_core.domain.strategy_execution_events import (
    CLAIM_ACQUIRED_EVENT,
    CLAIM_RELEASED_EVENT,
)


def handle_doc_claim_acquire(request: FunctionCallRequest) -> HandlerOutcome:
    payload, invalid = _model(request, StrategyDocClaimAcquireRequest)
    if invalid:
        return invalid
    from yoke_core.domain.db_helpers import connect

    with connect() as conn:
        project, error = _project(conn, request)
        if error:
            return error
        try:
            claim = acquire_session_doc_claim(
                conn,
                project_id=int(project.id),
                slug=payload.slug,
                session_id=_session_id(request),
                actor_id=_actor_id(request),
                reason=payload.reason,
            )
        except StrategyDocClaimConflictError as exc:
            return _error("document_already_claimed", str(exc))
        except StrategyDocMissingError as exc:
            return _error("unknown_document", str(exc))
        except (
            StrategyDocClaimAuthorizationError,
            StrategyExecutionError,
        ) as exc:
            return _error("document_claim_refused", str(exc))
    _emit_claim_event(CLAIM_ACQUIRED_EVENT, request, str(project.slug), claim)
    return _claim_outcome(project, claim)


def handle_doc_claim_release(request: FunctionCallRequest) -> HandlerOutcome:
    payload, invalid = _model(request, StrategyDocClaimReleaseRequest)
    if invalid:
        return invalid
    from yoke_core.domain.db_helpers import connect

    with connect() as conn:
        project, error = _project(conn, request)
        if error:
            return error
        try:
            released = release_session_doc_claim(
                conn,
                project_id=int(project.id),
                slug=payload.slug,
                session_id=_session_id(request),
                actor_id=_actor_id(request),
                reason=payload.reason,
            )
        except StrategyDocClaimAuthorizationError as exc:
            return _error("document_claim_denied", str(exc))
        except StrategyExecutionError as exc:
            return _error("document_claim_release_refused", str(exc))
    _emit_claim_event(CLAIM_RELEASED_EVENT, request, str(project.slug), released)
    return _claim_outcome(project, released)


def handle_doc_claim_list(request: FunctionCallRequest) -> HandlerOutcome:
    payload, invalid = _model(request, StrategyDocClaimListRequest)
    if invalid:
        return invalid
    from yoke_core.domain.db_helpers import connect

    with connect() as conn:
        project, error = _project(conn, request)
        if error:
            return error
        claims = list_strategy_doc_claims(
            conn,
            project_id=int(project.id),
            active_only=payload.active_only,
        )
    return HandlerOutcome(
        result_payload=StrategyDocClaimListResponse(
            project_id=int(project.id),
            project_slug=str(project.slug),
            claims=claims,
        ).model_dump(),
        primary_success=True,
    )


def _claim_outcome(project: Any, claim: dict) -> HandlerOutcome:
    return HandlerOutcome(
        result_payload=StrategyDocClaimResponse(
            project_id=int(project.id),
            project_slug=str(project.slug),
            claim=claim,
        ).model_dump(),
        primary_success=True,
    )


def _emit_claim_event(
    name: str,
    request: FunctionCallRequest,
    project_slug: str,
    context: dict,
) -> None:
    session_id: Optional[str] = _session_id(request) or None
    _events.emit_event(
        name,
        event_kind="workflow",
        event_type="strategy_doc",
        source_type="agent",
        session_id=session_id,
        severity="INFO",
        outcome="completed",
        project=project_slug,
        context=dict(context, owner_kind="session"),
    )


__all__ = [
    "handle_doc_claim_acquire",
    "handle_doc_claim_list",
    "handle_doc_claim_release",
]
