"""Handlers for ``strategy.doc.archive`` / ``strategy.doc.unarchive``.

Flip a strategy doc's archived state on its ``strategy_docs`` row.
Archiving stamps ``archived_at`` (the doc leaves the live corpus
directory and renders to ``.yoke/strategy/archive/<slug>.md``);
unarchiving clears it. The doc stays a full, editable row either way —
nothing is deleted, so ``strategy.doc.unarchive`` fully restores it.

Write gate mirrors ``strategy.doc.create`` rather than
``strategy.doc.replace``: archiving is an operator/admin state flip, not
a strategize-session content write, so the caller need NOT hold the
STRATEGIZE/FEED process claim — but the flip is refused while a FOREIGN
session holds that live claim, so it never races an in-flight strategize.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from yoke_core.domain import events as _events
from yoke_core.domain import strategy_docs as _docs
from yoke_core.domain.handlers.strategy_docs import (
    _err,
    _validate,
    foreign_strategy_claim_holder,
)
from yoke_core.domain.handlers.strategy_docs_project import resolve_request_project
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    HandlerOutcome,
)


STRATEGY_DOC_ARCHIVED_EVENT_NAME = "StrategyDocArchived"
STRATEGY_DOC_UNARCHIVED_EVENT_NAME = "StrategyDocUnarchived"


class DocArchiveRequest(BaseModel):
    slug: str = Field(..., min_length=1, description="Strategy doc slug.")


class DocArchiveResponse(BaseModel):
    project_id: int
    project_slug: str
    slug: str
    archived: bool
    archived_at: Optional[str] = None
    # False when the doc was already in the requested state (idempotent no-op).
    changed: bool = False


def _emit_archive_event(
    event_name: str, *, session_id: str, project: Any, result: Dict[str, Any],
) -> None:
    """Telemetry after the durable flip; best-effort (the row is authority)."""
    _events.emit_event(
        event_name,
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
            "archived": result["archived"],
        },
    )


def _handle_set_archived(
    request: FunctionCallRequest,
    *,
    archived: bool,
    function_id: str,
    event_name: str,
) -> HandlerOutcome:
    payload, err = _validate(request, DocArchiveRequest, function_id)
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
            verb = "archive" if archived else "unarchive"
            return _err(
                "archive_blocked_by_live_process_claim",
                f"a strategize/feed session currently owns project "
                f"{project.slug!r}'s strategy write window (session "
                f"{holder!r} holds the live STRATEGIZE/FEED process "
                f"work-claim). Wait for that session to finish, then "
                f"{verb} the doc again.",
            )
        try:
            result = _docs.set_doc_archived(
                conn, project.id, payload.slug, archived=archived,
            )
        except _docs.UnknownStrategyDocError as exc:
            return _err("unknown_slug", str(exc))
        except _docs.StrategyDocMissingError as exc:
            return _err("doc_not_seeded", str(exc))

    if result["changed"]:
        # A no-op flip (already in the requested state) advances nothing —
        # skip the event, mirroring the no-op-write skip in doc.replace.
        _emit_archive_event(
            event_name, session_id=session_id, project=project, result=result,
        )
    return HandlerOutcome(
        result_payload=DocArchiveResponse(
            project_id=project.id, project_slug=project.slug, **result,
        ).model_dump(),
        primary_success=True,
    )


def handle_doc_archive(request: FunctionCallRequest) -> HandlerOutcome:
    return _handle_set_archived(
        request,
        archived=True,
        function_id="strategy.doc.archive",
        event_name=STRATEGY_DOC_ARCHIVED_EVENT_NAME,
    )


def handle_doc_unarchive(request: FunctionCallRequest) -> HandlerOutcome:
    return _handle_set_archived(
        request,
        archived=False,
        function_id="strategy.doc.unarchive",
        event_name=STRATEGY_DOC_UNARCHIVED_EVENT_NAME,
    )


REGISTRATIONS: List[Dict[str, Any]] = [
    {
        "function_id": "strategy.doc.archive",
        "handler": handle_doc_archive,
        "request_model": DocArchiveRequest,
        "response_model": DocArchiveResponse,
        "stability": "stable",
        "owner_module": "yoke_core.domain.handlers.strategy_docs_archive",
        "target_kinds": ["global"],
        "side_effects": ["db_write", "event_emit"],
        "emitted_event_names": [STRATEGY_DOC_ARCHIVED_EVENT_NAME],
        "guardrails": ["foreign_process_claim_refused"],
        "adapter_status": "live",
        "claim_required_kind": None,
        "ambient_session_required": False,
    },
    {
        "function_id": "strategy.doc.unarchive",
        "handler": handle_doc_unarchive,
        "request_model": DocArchiveRequest,
        "response_model": DocArchiveResponse,
        "stability": "stable",
        "owner_module": "yoke_core.domain.handlers.strategy_docs_archive",
        "target_kinds": ["global"],
        "side_effects": ["db_write", "event_emit"],
        "emitted_event_names": [STRATEGY_DOC_UNARCHIVED_EVENT_NAME],
        "guardrails": ["foreign_process_claim_refused"],
        "adapter_status": "live",
        "claim_required_kind": None,
        "ambient_session_required": False,
    },
]


__all__ = [
    "DocArchiveRequest",
    "DocArchiveResponse",
    "REGISTRATIONS",
    "STRATEGY_DOC_ARCHIVED_EVENT_NAME",
    "STRATEGY_DOC_UNARCHIVED_EVENT_NAME",
    "handle_doc_archive",
    "handle_doc_unarchive",
]
