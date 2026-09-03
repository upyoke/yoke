"""Registered review and execution surfaces for strategy documents."""

from __future__ import annotations

from typing import Any, Optional

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_core.domain import events as _events
from yoke_core.domain.handlers.strategy_doc_surface_models import (
    EmptyRequest,
    StrategyExecutionClaimBreakGlassRequest,
    StrategyExecutionClaimReleaseRequest,
    StrategyExecutionLinkRequest,
    StrategyExecutionResponse,
)
from yoke_core.domain.handlers.strategy_docs_claims import (
    session_holds_strategy_claim,
)
from yoke_core.domain.handlers.strategy_docs_project import resolve_request_project
from yoke_core.domain.strategy_doc_surfaces import (
    get_blitz_surface,
)
from yoke_core.domain.strategy_docs import StrategyDocMissingError
from yoke_core.domain.strategy_execution import (
    StrategyDocClaimAuthorizationError,
    StrategyDocClaimConflictError,
    StrategyExecutionError,
    acquire_strategy_doc_claim,
    authorize_strategy_doc_write,
    link_execution_document,
    release_strategy_doc_claim,
)
from yoke_core.domain.strategy_execution_events import (
    CLAIM_ACQUIRED_EVENT,
    CLAIM_BREAK_GLASS_EVENT,
    CLAIM_RELEASED_EVENT,
    REVISION_RESTORED_EVENT,
)


def _error(code: str, message: str) -> HandlerOutcome:
    return HandlerOutcome(
        result_payload={},
        primary_success=False,
        error=FunctionError(code=code, message=message),
    )


def _model(request: FunctionCallRequest, model: Any):
    try:
        return model.model_validate(request.payload or {}), None
    except Exception as exc:
        return None, _error("invalid_payload", f"payload invalid: {exc}")


def _actor_id(request: FunctionCallRequest) -> Optional[int]:
    value = request.actor.actor_id
    return int(value) if value is not None and str(value).isdigit() else None


def _session_id(request: FunctionCallRequest) -> str:
    return str(request.actor.session_id or "")


def _item_id(request: FunctionCallRequest) -> tuple[Optional[int], Optional[HandlerOutcome]]:
    if request.target.kind != "item" or request.target.item_id is None:
        return None, _error(
            "invalid_target", "target must carry kind='item' and item_id",
        )
    return int(request.target.item_id), None


def _project(conn: Any, request: FunctionCallRequest):
    if request.target.kind != "global":
        return None, _error(
            "invalid_target", "strategy document reads use a global target",
        )
    return resolve_request_project(conn, request)


def _doc_write_allowed(
    conn: Any,
    request: FunctionCallRequest,
    project: Any,
    slug: str,
) -> Optional[HandlerOutcome]:
    session_id = _session_id(request)
    if not session_id:
        return _error("invalid_payload", "actor.session_id is required")
    try:
        claimed = authorize_strategy_doc_write(
            conn,
            project_id=int(project.id),
            slug=slug,
            session_id=session_id,
        )
    except StrategyDocClaimAuthorizationError as exc:
        return _error("strategy_document_claim_denied", str(exc))
    if claimed or session_holds_strategy_claim(
        conn, session_id, str(project.slug),
    ):
        return None
    return _error(
        "strategy_claim_required",
        "unclaimed strategy documents require the calling session's "
        "strategy control-plane process claim",
    )


def handle_execution_get(request: FunctionCallRequest) -> HandlerOutcome:
    _, invalid = _model(request, EmptyRequest)
    if invalid:
        return invalid
    item_id, error = _item_id(request)
    if error:
        return error
    from yoke_core.domain.db_helpers import connect
    with connect() as conn:
        try:
            execution = get_blitz_surface(conn, item_id)
        except StrategyExecutionError as exc:
            return _error("invalid_blitz", str(exc))
    return _execution_outcome(item_id, execution)


def handle_execution_link(request: FunctionCallRequest) -> HandlerOutcome:
    payload, invalid = _model(request, StrategyExecutionLinkRequest)
    if invalid:
        return invalid
    item_id, error = _item_id(request)
    if error:
        return error
    from yoke_core.domain.db_helpers import connect
    with connect() as conn:
        project_id = conn.execute(
            "SELECT project_id FROM items WHERE id = %s", (item_id,),
        ).fetchone()
        if project_id is None:
            return _error("unknown_item", f"item {item_id} does not exist")
        try:
            link = link_execution_document(
                conn,
                item_id=item_id,
                project_id=int(project_id[0]),
                slug=payload.slug,
                actor_id=_actor_id(request),
                session_id=_session_id(request) or None,
            )
            # A Blitz answers with the shell it executes; every other item
            # answers with the link itself, because membership in a strategy
            # document is the whole fact it just recorded.
            execution = (
                get_blitz_surface(conn, item_id)
                if _is_blitz_item(conn, item_id)
                else {"link": link}
            )
        except (StrategyExecutionError, StrategyDocMissingError) as exc:
            return _error("execution_link_refused", str(exc))
    return _execution_outcome(item_id, execution)


def _is_blitz_item(conn: Any, item_id: int) -> bool:
    from yoke_core.domain.strategy_execution_state import BLITZ_WORKFLOW_ID

    row = conn.execute(
        "SELECT workflow_id FROM items WHERE id = %s", (int(item_id),),
    ).fetchone()
    return row is not None and str(row[0]) == BLITZ_WORKFLOW_ID


def handle_claim_acquire(request: FunctionCallRequest) -> HandlerOutcome:
    _, invalid = _model(request, EmptyRequest)
    if invalid:
        return invalid
    item_id, error = _item_id(request)
    if error:
        return error
    from yoke_core.domain.db_helpers import connect
    with connect() as conn:
        try:
            claim = acquire_strategy_doc_claim(
                conn,
                item_id=item_id,
                session_id=_session_id(request),
                actor_id=_actor_id(request),
            )
            execution = get_blitz_surface(conn, item_id)
        except StrategyDocClaimConflictError as exc:
            return _error("document_already_claimed", str(exc))
        except StrategyExecutionError as exc:
            return _error("document_claim_refused", str(exc))
    _emit(CLAIM_ACQUIRED_EVENT, request, execution["item"]["project_slug"], claim)
    return _execution_outcome(item_id, execution)


def handle_claim_release(request: FunctionCallRequest) -> HandlerOutcome:
    payload, invalid = _model(request, StrategyExecutionClaimReleaseRequest)
    if invalid:
        return invalid
    item_id, error = _item_id(request)
    if error:
        return error
    from yoke_core.domain.db_helpers import connect
    with connect() as conn:
        try:
            result = release_strategy_doc_claim(
                conn,
                item_id=item_id,
                session_id=_session_id(request),
                actor_id=_actor_id(request),
                reason=payload.reason,
            )
            execution = get_blitz_surface(conn, item_id)
        except StrategyExecutionError as exc:
            return _error("document_claim_release_refused", str(exc))
    _emit(CLAIM_RELEASED_EVENT, request, execution["item"]["project_slug"], result)
    return _execution_outcome(item_id, execution)


def handle_claim_break_glass_release(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    payload, invalid = _model(
        request, StrategyExecutionClaimBreakGlassRequest,
    )
    if invalid:
        return invalid
    item_id, error = _item_id(request)
    if error:
        return error
    from yoke_core.domain.db_helpers import connect
    with connect() as conn:
        try:
            result = release_strategy_doc_claim(
                conn,
                item_id=item_id,
                session_id=_session_id(request),
                actor_id=_actor_id(request),
                break_glass=True,
                reason=payload.reason,
            )
            execution = get_blitz_surface(conn, item_id)
        except StrategyExecutionError as exc:
            return _error("document_claim_release_refused", str(exc))
    _emit(
        CLAIM_BREAK_GLASS_EVENT,
        request,
        execution["item"]["project_slug"],
        result,
    )
    return _execution_outcome(item_id, execution)


def _execution_outcome(item_id: int, execution: dict) -> HandlerOutcome:
    return HandlerOutcome(
        result_payload=StrategyExecutionResponse(
            item_id=item_id, execution=execution,
        ).model_dump(),
        primary_success=True,
    )


def _emit(
    name: str, request: FunctionCallRequest, project_slug: str, context: dict,
) -> None:
    _events.emit_event(
        name,
        event_kind="workflow",
        event_type="strategy_doc",
        source_type="agent",
        session_id=_session_id(request) or None,
        severity="WARN" if name == CLAIM_BREAK_GLASS_EVENT else "INFO",
        outcome="completed",
        project=project_slug,
        context=context,
    )


__all__ = [
    "CLAIM_ACQUIRED_EVENT",
    "CLAIM_BREAK_GLASS_EVENT",
    "CLAIM_RELEASED_EVENT",
    "REVISION_RESTORED_EVENT",
    "handle_claim_acquire",
    "handle_claim_break_glass_release",
    "handle_claim_release",
    "handle_execution_get",
    "handle_execution_link",
]
