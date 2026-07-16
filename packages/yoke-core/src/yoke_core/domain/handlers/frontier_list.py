"""``frontier.list`` read handler: what runs next and what waits on what.

Read-only sibling of the side-effectful ``charge.schedule`` wrapper (in
:mod:`sessions_orchestration`): same scheduler underneath, but this
handler suppresses every telemetry write (``emit_events=False``) so a
browser poll never leaves event rows behind. The row shapes live in
:mod:`yoke_core.domain.frontier_list_read`.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class FrontierListRequest(BaseModel):
    project: Optional[str] = None
    wip_cap: Optional[int] = None


class FrontierListResponse(BaseModel):
    fields: Dict[str, List[str]]
    ready_rows: List[Dict[str, Any]]
    blocked_rows: List[Dict[str, Any]]
    frozen_count: int
    wip_cap: int
    wip_active: int


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


def handle_frontier_list(request: FunctionCallRequest) -> HandlerOutcome:
    if request.target.kind != "global":
        return _error(
            "target_invalid",
            "frontier.list requires target.kind='global'",
            jsonpath="$.target.kind",
        )
    payload = request.payload or {}
    project = payload.get("project")
    wip_cap = payload.get("wip_cap")
    if project is not None and not isinstance(project, str):
        return _error(
            "payload_invalid",
            "project must be a string when present",
            jsonpath="$.payload.project",
        )
    if wip_cap is not None and (
        isinstance(wip_cap, bool) or not isinstance(wip_cap, int)
    ):
        return _error(
            "payload_invalid",
            "wip_cap must be an integer when present",
            jsonpath="$.payload.wip_cap",
        )

    from yoke_core.domain.frontier_list_read import list_frontier

    try:
        result = list_frontier(project=project, wip_cap=wip_cap)
    except ValueError as exc:
        # resolve_session_project_scope names the unknown project and the
        # registered set.
        return _error("not_found", str(exc), jsonpath="$.payload.project")
    return HandlerOutcome(result_payload=result, primary_success=True)


__all__ = [
    "FrontierListRequest",
    "FrontierListResponse",
    "handle_frontier_list",
]
