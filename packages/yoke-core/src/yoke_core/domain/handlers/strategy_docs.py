"""Handlers for the ``strategy.doc.*`` / ``strategy.render.run`` family.

The Yoke DB ``strategy_docs`` table is the per-project read/write
authority for strategy documents; each project's ``.yoke/strategy/``
files are a gitignored local rendered view (regenerated cache, the
``.yoke/BOARD.md`` precedent; DB is the sole durable authority) written
only by ``strategy.render.run`` — and by the
``strategy.ingest.run`` write-back in the sibling
:mod:`yoke_core.domain.handlers.strategy_docs_ingest`, which
re-renders the docs it ingests. Cold-start seeding lives in
:mod:`yoke_core.domain.handlers.strategy_docs_seed`.

Project context rides on ``target.project_id`` (client-resolved slug or
id; the dispatcher's session inference is the fallback) and resolves
server-side via
:mod:`yoke_core.domain.handlers.strategy_docs_project`.

Write gate (``strategy.doc.replace``): an execution document with an
active item-owned claim may only be revised by the session holding its
owning Blitz item's live work claim. For an unclaimed document, the
legacy project strategy window remains in force: the calling session
must hold an ACTIVE ``work_claims`` row with ``target_kind='process'``
whose ``conflict_group`` is the TARGET PROJECT's strategy control-plane
group (``STRATEGIZE`` or ``FEED`` both satisfy it).

``strategy.render.run`` does no file I/O: it returns the
per-doc rendered file texts and the CALLER writes them — the CLI
adapter resolves the checkout anchor client-side (``--target-root`` /
``$YOKE_RENDER_TARGET_ROOT`` / repo-root helper) and lands the files
via :func:`yoke_core.domain.strategy_docs_render.write_rendered_files`,
so the same envelope works in-process and over https where the server
has no checkout.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from yoke_core.domain import events as _events
from yoke_core.domain import strategy_docs as _docs
from yoke_core.domain.handlers.strategy_docs_claims import (
    CLAIM_ACQUIRE_RECIPE,
    foreign_strategy_claim_holder,  # noqa: F401 — re-export for ingest/tests
)
from yoke_core.domain.handlers.strategy_docs_models import (
    DocGetRequest,
    DocGetResponse,
    DocListRequest,
    DocListResponse,
    DocReplaceRequest,
    DocReplaceResponse,
    RenderRequest,
    RenderResponse,
)
from yoke_core.domain.handlers.strategy_docs_project import (
    resolve_request_project,
)
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)

STRATEGY_DOC_REPLACED_EVENT_NAME = "StrategyDocReplaced"


def _bad_request(message: str, *, jsonpath: str = "$.payload") -> HandlerOutcome:
    return HandlerOutcome(
        result_payload={},
        primary_success=False,
        error=FunctionError(
            code="invalid_payload", message=message, jsonpath=jsonpath,
        ),
    )


def _err(code: str, message: str) -> HandlerOutcome:
    return HandlerOutcome(
        result_payload={},
        primary_success=False,
        error=FunctionError(code=code, message=message),
    )


def _validate(request: FunctionCallRequest, model, function_id: str):
    """Return ``(payload, error_outcome)`` — exactly one is set."""
    if request.target.kind != "global":
        return None, _bad_request(
            f"target.kind must be 'global' ({function_id} has no item "
            "binding; project context rides on target.project_id)",
            jsonpath="$.target.kind",
        )
    try:
        return model.model_validate(request.payload or {}), None
    except Exception as exc:
        return None, _bad_request(f"payload invalid: {exc}")


def handle_doc_list(request: FunctionCallRequest) -> HandlerOutcome:
    _, err = _validate(request, DocListRequest, "strategy.doc.list")
    if err is not None:
        return err
    from yoke_core.domain.db_helpers import connect

    with connect() as conn:
        project, perr = resolve_request_project(conn, request)
        if perr is not None:
            return perr
        docs = _docs.list_docs(conn, project.id)
    return HandlerOutcome(
        result_payload=DocListResponse(
            project_id=project.id, project_slug=project.slug, docs=docs,
        ).model_dump(),
        primary_success=True,
    )


def handle_doc_get(request: FunctionCallRequest) -> HandlerOutcome:
    payload, err = _validate(request, DocGetRequest, "strategy.doc.get")
    if err is not None:
        return err
    from yoke_core.domain.db_helpers import connect

    with connect() as conn:
        project, perr = resolve_request_project(conn, request)
        if perr is not None:
            return perr
        try:
            doc = _docs.get_doc(conn, project.id, payload.slug)
        except _docs.UnknownStrategyDocError as exc:
            return _err("unknown_slug", str(exc))
        except _docs.StrategyDocMissingError as exc:
            return _err("doc_not_seeded", str(exc))
    return HandlerOutcome(
        result_payload=DocGetResponse(
            project_id=project.id, project_slug=project.slug, **doc,
        ).model_dump(),
        primary_success=True,
    )


def _numeric_actor_id(value: Any) -> Optional[int]:
    text = str(value).strip() if value is not None else ""
    return int(text) if text.isdigit() else None


def emit_doc_replaced(
    *, session_id: str, project: Any, result: Dict[str, Any], source: str,
) -> None:
    """Telemetry after the durable write; best-effort (the row is
    authoritative)."""
    _events.emit_event(
        STRATEGY_DOC_REPLACED_EVENT_NAME,
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
            "old_bytes": result["old_bytes"],
            "new_bytes": result["new_bytes"],
            "source": source,
        },
    )


def handle_doc_replace(request: FunctionCallRequest) -> HandlerOutcome:
    from yoke_core.domain.handlers.strategy_doc_replace import (
        handle_doc_replace as replace,
    )

    return replace(request)


def handle_render(request: FunctionCallRequest) -> HandlerOutcome:
    payload, err = _validate(request, RenderRequest, "strategy.render.run")
    if err is not None:
        return err
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.strategy_docs_render import render_file_map

    with connect() as conn:
        project, perr = resolve_request_project(conn, request)
        if perr is not None:
            return perr
        try:
            files = render_file_map(conn, project.id, payload.slugs or None)
        except _docs.UnknownStrategyDocError as exc:
            return _err("unknown_slug", str(exc))
        except _docs.StrategyDocMissingError as exc:
            return _err("doc_not_seeded", str(exc))
    response = RenderResponse(
        project_id=project.id, project_slug=project.slug, docs=files,
    )
    return HandlerOutcome(
        result_payload=response.model_dump(),
        primary_success=True,
    )


REGISTRATIONS: List[Dict[str, Any]] = [
    {
        "function_id": "strategy.doc.list",
        "handler": handle_doc_list,
        "request_model": DocListRequest,
        "response_model": DocListResponse,
        "stability": "stable",
        "owner_module": "yoke_core.domain.handlers.strategy_docs",
        "target_kinds": ["global"],
        "side_effects": [],
        "emitted_event_names": [],
        "guardrails": [],
        "adapter_status": "live",
        "claim_required_kind": None,
    },
    {
        "function_id": "strategy.doc.get",
        "handler": handle_doc_get,
        "request_model": DocGetRequest,
        "response_model": DocGetResponse,
        "stability": "stable",
        "owner_module": "yoke_core.domain.handlers.strategy_docs",
        "target_kinds": ["global"],
        "side_effects": [],
        "emitted_event_names": [],
        "guardrails": [],
        "adapter_status": "live",
        "claim_required_kind": None,
    },
    {
        "function_id": "strategy.doc.replace",
        "handler": handle_doc_replace,
        "request_model": DocReplaceRequest,
        "response_model": DocReplaceResponse,
        "stability": "stable",
        "owner_module": "yoke_core.domain.handlers.strategy_docs",
        "target_kinds": ["global"],
        "side_effects": ["db_write", "event_emit"],
        "emitted_event_names": [STRATEGY_DOC_REPLACED_EVENT_NAME],
        "guardrails": [
            "strategy_process_claim_required",
            "shrink_guard",
            "compare_and_swap_base",
        ],
        "adapter_status": "live",
        "claim_required_kind": None,
    },
    {
        "function_id": "strategy.render.run",
        "handler": handle_render,
        "request_model": RenderRequest,
        "response_model": RenderResponse,
        "stability": "stable",
        "owner_module": "yoke_core.domain.handlers.strategy_docs",
        "target_kinds": ["global"],
        "side_effects": [],
        "emitted_event_names": [],
        "guardrails": ["client_side_file_io"],
        "adapter_status": "live",
        "claim_required_kind": None,
    },
]


__all__ = [
    "CLAIM_ACQUIRE_RECIPE",
    "DocGetRequest",
    "DocGetResponse",
    "DocListRequest",
    "DocListResponse",
    "DocReplaceRequest",
    "DocReplaceResponse",
    "REGISTRATIONS",
    "RenderRequest",
    "RenderResponse",
    "STRATEGY_DOC_REPLACED_EVENT_NAME",
    "emit_doc_replaced",
    "foreign_strategy_claim_holder",
    "handle_doc_get",
    "handle_doc_list",
    "handle_doc_replace",
    "handle_render",
]
