"""Template function handlers (``templates.list`` / ``templates.fetch``).

Like the project-install family, these run the client-side template layer
on whatever host dispatches them — ``templates.fetch.run`` writes files on
THIS machine, so the family is meaningful in-process and nonsensical to
relay to a cloud env. The handler resolves the listing/bundle itself (the
active connection's transport decides https-GET vs in-process build).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from yoke_cli.config import template_fetch
from yoke_cli.config.template_fetch import TemplateFetchError
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class TemplatesListRequest(BaseModel):
    config_path: Optional[str] = None


class TemplatesListResponse(BaseModel):
    templates: List[Dict[str, Any]]
    source: str


class TemplatesFetchRequest(BaseModel):
    template: str
    dest: Optional[str] = None
    only: Optional[str] = None
    force: bool = False
    include_source_dev_admin: bool = False
    config_path: Optional[str] = None


class TemplatesFetchResponse(BaseModel):
    operation: str
    template: str
    dest: str
    source: str
    yoke_version: str
    product_boundary: str
    only: Optional[str] = None
    files_written: List[str]
    files_skipped_existing: List[str]
    binary_files_skipped: int


def handle_templates_list(request: FunctionCallRequest) -> HandlerOutcome:
    payload = request.payload or {}

    def _list() -> Dict[str, Any]:
        templates, source = template_fetch.resolve_listing(
            payload.get("config_path")
        )
        return {"templates": templates, "source": source}

    return _outcome(_list)


def handle_templates_fetch(request: FunctionCallRequest) -> HandlerOutcome:
    payload = request.payload or {}
    return _outcome(lambda: template_fetch.fetch(
        str(payload.get("template") or ""),
        payload.get("dest"),
        only=payload.get("only"),
        force=bool(payload.get("force")),
        config_path=payload.get("config_path"),
        include_source_dev_admin=bool(payload.get("include_source_dev_admin")),
    ))


def _outcome(operation) -> HandlerOutcome:
    try:
        result = operation()
    except TemplateFetchError as exc:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="template_fetch_failed",
                message=str(exc),
            ),
        )
    return HandlerOutcome(result_payload=result, primary_success=True)


__all__ = [
    "TemplatesFetchRequest",
    "TemplatesFetchResponse",
    "TemplatesListRequest",
    "TemplatesListResponse",
    "handle_templates_fetch",
    "handle_templates_list",
]
