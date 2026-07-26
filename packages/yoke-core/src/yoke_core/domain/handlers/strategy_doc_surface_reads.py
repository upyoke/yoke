"""Strategy corpus review, history, restore, and ancestry handlers."""

from __future__ import annotations

from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome
from yoke_core.domain.handlers.strategy_doc_surface_models import (
    EmptyRequest,
    StrategyCoordinationAppendRequest,
    StrategyCoordinationAppendResponse,
    StrategyParentSetRequest,
    StrategyParentSetResponse,
    StrategyRevisionDiffRequest,
    StrategyRevisionDiffResponse,
    StrategyRevisionRestoreRequest,
    StrategyRevisionRestoreResponse,
    StrategySurfaceGetRequest,
    StrategySurfaceGetResponse,
    StrategySurfaceListResponse,
)
from yoke_core.domain.strategy_coordination import append_strategy_coordination
from yoke_core.domain.handlers.strategy_doc_surfaces import (
    REVISION_RESTORED_EVENT,
    _actor_id,
    _doc_write_allowed,
    _emit,
    _error,
    _model,
    _project,
)
from yoke_core.domain.strategy_doc_history import (
    StrategyDocRevisionMissingError,
    diff_doc_revisions,
    restore_doc_revision,
)
from yoke_core.domain.strategy_doc_surfaces import (
    get_strategy_surface,
    list_strategy_surfaces,
    set_strategy_doc_parent,
    strategy_write_activity,
)
from yoke_core.domain.strategy_docs import (
    StrategyDocConflictError,
    StrategyDocMissingError,
)
from yoke_core.domain.strategy_execution import StrategyExecutionError
from yoke_core.domain.strategy_execution_events import (
    COORDINATION_APPENDED_EVENT,
)


def handle_surface_list(request: FunctionCallRequest) -> HandlerOutcome:
    _, invalid = _model(request, EmptyRequest)
    if invalid:
        return invalid
    from yoke_core.domain.db_helpers import connect
    with connect() as conn:
        project, error = _project(conn, request)
        if error:
            return error
        docs = list_strategy_surfaces(conn, int(project.id))
        writes = strategy_write_activity(conn, int(project.id))
    return HandlerOutcome(
        result_payload=StrategySurfaceListResponse(
            project_id=project.id,
            project_slug=project.slug,
            docs=docs,
            writes=writes,
        ).model_dump(),
        primary_success=True,
    )


def handle_surface_get(request: FunctionCallRequest) -> HandlerOutcome:
    payload, invalid = _model(request, StrategySurfaceGetRequest)
    if invalid:
        return invalid
    from yoke_core.domain.db_helpers import connect
    with connect() as conn:
        project, error = _project(conn, request)
        if error:
            return error
        try:
            document = get_strategy_surface(conn, int(project.id), payload.slug)
        except StrategyDocMissingError as exc:
            return _error("doc_not_seeded", str(exc))
    return HandlerOutcome(
        result_payload=StrategySurfaceGetResponse(
            project_id=project.id,
            project_slug=project.slug,
            document=document,
        ).model_dump(),
        primary_success=True,
    )


def handle_revision_diff(request: FunctionCallRequest) -> HandlerOutcome:
    payload, invalid = _model(request, StrategyRevisionDiffRequest)
    if invalid:
        return invalid
    from yoke_core.domain.db_helpers import connect
    with connect() as conn:
        project, error = _project(conn, request)
        if error:
            return error
        try:
            comparison = diff_doc_revisions(
                conn, project.id, payload.slug,
                payload.from_revision, payload.to_revision,
            )
        except StrategyDocRevisionMissingError as exc:
            return _error("unknown_revision", str(exc))
    return HandlerOutcome(
        result_payload=StrategyRevisionDiffResponse(
            project_id=project.id,
            project_slug=project.slug,
            comparison=comparison,
        ).model_dump(),
        primary_success=True,
    )


def handle_revision_restore(request: FunctionCallRequest) -> HandlerOutcome:
    payload, invalid = _model(request, StrategyRevisionRestoreRequest)
    if invalid:
        return invalid
    from yoke_core.domain.db_helpers import connect
    with connect() as conn:
        project, error = _project(conn, request)
        if error:
            return error
        denied = _doc_write_allowed(conn, request, project, payload.slug)
        if denied:
            return denied
        try:
            result = restore_doc_revision(
                conn, project.id, payload.slug, payload.revision,
                base_updated_at=payload.base_updated_at,
                actor_id=_actor_id(request),
                session_id=str(request.actor.session_id or "") or None,
            )
            actor_id = _actor_id(request)
            if actor_id is not None:
                from yoke_core.domain.strategy_review_requests import (
                    ensure_current_strategy_revision_review,
                )

                ensure_current_strategy_revision_review(
                    conn,
                    project_id=project.id,
                    slug=payload.slug,
                    originator_actor_id=actor_id,
                    session_id=str(request.actor.session_id or ""),
                )
        except StrategyDocRevisionMissingError as exc:
            return _error("unknown_revision", str(exc))
        except StrategyDocConflictError as exc:
            return _error("restore_conflict", str(exc))
    _emit(REVISION_RESTORED_EVENT, request, project.slug, result)
    return HandlerOutcome(
        result_payload=StrategyRevisionRestoreResponse(
            project_id=project.id, project_slug=project.slug, result=result,
        ).model_dump(),
        primary_success=True,
    )


def handle_parent_set(request: FunctionCallRequest) -> HandlerOutcome:
    payload, invalid = _model(request, StrategyParentSetRequest)
    if invalid:
        return invalid
    from yoke_core.domain.db_helpers import connect
    with connect() as conn:
        project, error = _project(conn, request)
        if error:
            return error
        denied = _doc_write_allowed(conn, request, project, payload.slug)
        if denied:
            return denied
        try:
            result = set_strategy_doc_parent(
                conn,
                project_id=project.id,
                slug=payload.slug,
                parent_slug=payload.parent_slug,
            )
        except (StrategyExecutionError, StrategyDocMissingError) as exc:
            return _error("invalid_parent", str(exc))
    return HandlerOutcome(
        result_payload=StrategyParentSetResponse(
            project_id=project.id, project_slug=project.slug, result=result,
        ).model_dump(),
        primary_success=True,
    )


def handle_coordination_append(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    payload, invalid = _model(request, StrategyCoordinationAppendRequest)
    if invalid:
        return invalid
    if not request.actor.session_id:
        return _error("actor_required", "actor.session_id is required")
    from yoke_core.domain.db_helpers import connect
    with connect() as conn:
        project, error = _project(conn, request)
        if error:
            return error
        try:
            result = append_strategy_coordination(
                conn,
                project_id=project.id,
                slug=payload.slug,
                section=payload.section,
                entry=payload.entry,
                actor_id=_actor_id(request),
                session_id=str(request.actor.session_id),
            )
        except StrategyDocMissingError as exc:
            return _error("doc_not_seeded", str(exc))
        except ValueError as exc:
            return _error("coordination_append_refused", str(exc))
    _emit(COORDINATION_APPENDED_EVENT, request, project.slug, result)
    return HandlerOutcome(
        result_payload=StrategyCoordinationAppendResponse(
            project_id=project.id, project_slug=project.slug, result=result,
        ).model_dump(),
        primary_success=True,
    )


__all__ = [
    "handle_coordination_append",
    "handle_parent_set",
    "handle_revision_diff",
    "handle_revision_restore",
    "handle_surface_get",
    "handle_surface_list",
]
