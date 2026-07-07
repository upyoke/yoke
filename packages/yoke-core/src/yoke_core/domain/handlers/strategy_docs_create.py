"""Handler for ``strategy.doc.create`` — add a new strategy-doc row."""

from __future__ import annotations

from typing import Any, Dict, List

from pydantic import BaseModel, Field

from yoke_core.domain import events as _events
from yoke_core.domain import strategy_docs as _docs
from yoke_core.domain import strategy_docs_create as _create
from yoke_core.domain.handlers.strategy_docs import (
    _err,
    _numeric_actor_id,
    _validate,
    foreign_strategy_claim_holder,
)
from yoke_core.domain.handlers.strategy_docs_project import resolve_request_project
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    HandlerOutcome,
)


STRATEGY_DOC_CREATED_EVENT_NAME = "StrategyDocCreated"


class DocCreateRequest(BaseModel):
    slug: str = Field(..., min_length=1, description="New strategy doc slug.")
    content: str = Field(..., description="Initial full doc content.")


class DocCreateResponse(BaseModel):
    project_id: int
    project_slug: str
    slug: str
    new_bytes: int
    updated_at: str


def emit_doc_created(
    *, session_id: str, project: Any, result: Dict[str, Any],
) -> None:
    """Telemetry after the durable create; best-effort."""
    _events.emit_event(
        STRATEGY_DOC_CREATED_EVENT_NAME,
        event_kind="workflow",
        event_type="strategy_doc",
        source_type="agent",
        session_id=session_id,
        severity="INFO",
        outcome="completed",
        project=project.slug,
        context={
            "slug": result["slug"],
            "project_id": project.id,
            "project_slug": project.slug,
            "new_bytes": result["new_bytes"],
        },
    )


def handle_doc_create(request: FunctionCallRequest) -> HandlerOutcome:
    payload, err = _validate(request, DocCreateRequest, "strategy.doc.create")
    if err is not None:
        return err
    session_id = request.actor.session_id or ""

    from yoke_core.domain.db_helpers import connect

    with connect() as conn:
        project, perr = resolve_request_project(conn, request)
        if perr is not None:
            return perr
        holder = foreign_strategy_claim_holder(conn, session_id, project.slug)
        if holder is not None:
            return _err(
                "create_blocked_by_live_process_claim",
                "a strategize/feed session currently owns project "
                f"{project.slug!r}'s strategy write window (session "
                f"{holder!r} holds the live STRATEGIZE/FEED process "
                "work-claim). Wait for that session to finish, render the "
                "fresh corpus, then create the doc again.",
            )
        try:
            result = _create.create_doc(
                conn,
                project.id,
                payload.slug,
                payload.content,
                _numeric_actor_id(request.actor.actor_id),
            )
        except _docs.UnknownStrategyDocError as exc:
            return _err("unknown_slug", str(exc))
        except _docs.EmptyStrategyDocError as exc:
            return _err("empty_content_refused", str(exc))
        except _create.DuplicateStrategyDocError as exc:
            return _err("doc_already_exists", str(exc))

    emit_doc_created(session_id=session_id, project=project, result=result)
    return HandlerOutcome(
        result_payload=DocCreateResponse(
            project_id=project.id, project_slug=project.slug, **result,
        ).model_dump(),
        primary_success=True,
    )


REGISTRATIONS: List[Dict[str, Any]] = [
    {
        "function_id": "strategy.doc.create",
        "handler": handle_doc_create,
        "request_model": DocCreateRequest,
        "response_model": DocCreateResponse,
        "stability": "stable",
        "owner_module": "yoke_core.domain.handlers.strategy_docs_create",
        "target_kinds": ["global"],
        "side_effects": ["db_write", "event_emit"],
        "emitted_event_names": [STRATEGY_DOC_CREATED_EVENT_NAME],
        "guardrails": [
            "unique_slug",
            "empty_content_refused",
            "foreign_process_claim_refused",
        ],
        "adapter_status": "live",
        "claim_required_kind": None,
        "ambient_session_required": False,
    },
]


__all__ = [
    "DocCreateRequest",
    "DocCreateResponse",
    "REGISTRATIONS",
    "STRATEGY_DOC_CREATED_EVENT_NAME",
    "handle_doc_create",
]
