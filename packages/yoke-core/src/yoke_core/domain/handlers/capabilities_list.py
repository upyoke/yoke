"""``projects.capabilities.list`` read handler: the capability roster view.

Read-only sibling of the capability-settings mutation handlers in
:mod:`projects_capability_settings`. The row shape, kind/state
derivation, GitHub freshness overlay, and non-secret settings summary
live in :mod:`yoke_core.domain.capabilities_list_read`.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class CapabilitiesListRequest(BaseModel):
    project: Optional[str] = None


class CapabilitiesListResponse(BaseModel):
    fields: List[str]
    rows: List[Dict[str, Any]]


def _error(
    code: str,
    message: str,
    *,
    jsonpath: Optional[str] = None,
) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message, jsonpath=jsonpath),
    )


def handle_capabilities_list(request: FunctionCallRequest) -> HandlerOutcome:
    if request.target.kind != "global":
        return _error(
            "target_invalid",
            "projects.capabilities.list requires target.kind='global'",
            jsonpath="$.target.kind",
        )
    payload = request.payload or {}
    project = payload.get("project")
    if project is not None and not isinstance(project, str):
        return _error(
            "payload_invalid",
            "project must be a string when present",
            jsonpath="$.payload.project",
        )

    from yoke_core.domain.capabilities_list_read import (
        CAPABILITY_LIST_FIELDS,
        list_capabilities,
    )

    try:
        rows = list_capabilities(project=project)
    except LookupError as exc:
        return _error(
            "not_found", str(exc), jsonpath="$.payload.project",
        )
    return HandlerOutcome(
        result_payload={
            "fields": list(CAPABILITY_LIST_FIELDS),
            "rows": rows,
        },
        primary_success=True,
    )


__all__ = [
    "CapabilitiesListRequest",
    "CapabilitiesListResponse",
    "handle_capabilities_list",
]
