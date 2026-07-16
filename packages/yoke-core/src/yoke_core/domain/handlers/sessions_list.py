"""``sessions.list`` read handler: the session roster steering view.

Sibling of :mod:`sessions_orchestration` (which owns the touch /
checkpoint / offer wrappers); this module is read-only. The row shape
and liveness derivation live in
:mod:`yoke_core.domain.sessions_list_read`.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class SessionsListRequest(BaseModel):
    project: Optional[str] = None
    liveness: Optional[str] = None
    limit: Optional[int] = None


class SessionsListResponse(BaseModel):
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


def handle_sessions_list(request: FunctionCallRequest) -> HandlerOutcome:
    if request.target.kind != "global":
        return _error(
            "target_invalid",
            "sessions.list requires target.kind='global'",
            jsonpath="$.target.kind",
        )
    payload = request.payload or {}
    project = payload.get("project")
    liveness = payload.get("liveness")
    limit = payload.get("limit")
    for key, value in (("project", project), ("liveness", liveness)):
        if value is not None and not isinstance(value, str):
            return _error(
                "payload_invalid",
                f"{key} must be a string when present",
                jsonpath=f"$.payload.{key}",
            )
    if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int)):
        return _error(
            "payload_invalid",
            "limit must be an integer when present",
            jsonpath="$.payload.limit",
        )

    from yoke_core.domain.sessions_list_read import (
        DEFAULT_SESSIONS_LIST_LIMIT,
        SESSION_LIST_FIELDS,
        list_sessions,
    )

    try:
        rows = list_sessions(
            project=project,
            liveness=liveness,
            limit=limit if limit is not None else DEFAULT_SESSIONS_LIST_LIMIT,
        )
    except ValueError as exc:
        return _error(
            "payload_invalid", str(exc), jsonpath="$.payload.liveness",
        )
    except LookupError as exc:
        return _error(
            "not_found", str(exc), jsonpath="$.payload.project",
        )
    return HandlerOutcome(
        result_payload={
            "fields": list(SESSION_LIST_FIELDS),
            "rows": rows,
        },
        primary_success=True,
    )


__all__ = [
    "SessionsListRequest",
    "SessionsListResponse",
    "handle_sessions_list",
]
