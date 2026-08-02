"""``sessions.list`` read handler: the session roster steering view.

Sibling of :mod:`sessions_orchestration` (which owns the touch /
checkpoint / offer wrappers); this module is read-only. The row shape
and liveness derivation live in
:mod:`yoke_core.domain.sessions_list_read`.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)

#: Row keys of the single-session liveness projection (``session_id`` filter).
SESSION_LIVENESS_FIELDS = ("session_id", "liveness", "ended_at", "activity_at")


def _session_liveness_row(session_id: str) -> Optional[Dict[str, Any]]:
    """One session's liveness projection, or ``None`` when unregistered."""
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.session_staleness import activity_is_stale
    from yoke_core.domain.sessions_list_read import (
        LIVENESS_ACTIVE,
        LIVENESS_ENDED,
        LIVENESS_STALE,
        _latest_activity,
    )

    conn = connect()
    try:
        row = conn.execute(
            "SELECT session_id, ended_at, last_heartbeat, last_tool_call_at, "
            "executor FROM harness_sessions WHERE session_id = %s",
            (session_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    activity_at, _parsed = _latest_activity(
        row["last_heartbeat"], row["last_tool_call_at"]
    )
    if row["ended_at"]:
        liveness = LIVENESS_ENDED
    elif activity_is_stale(activity_at, executor=row["executor"]):
        liveness = LIVENESS_STALE
    else:
        liveness = LIVENESS_ACTIVE
    return {
        "session_id": str(row["session_id"]),
        "liveness": liveness,
        "ended_at": "" if row["ended_at"] is None else str(row["ended_at"]),
        "activity_at": activity_at or "",
    }


class SessionsListRequest(BaseModel):
    project: Optional[str] = None
    liveness: Optional[str] = None
    limit: Optional[int] = None
    per_project: bool = False
    session_id: Optional[str] = Field(
        default=None,
        description=(
            "Return the liveness projection for exactly this session — "
            "fields session_id/liveness/ended_at/activity_at, one row or "
            "none. Other filters are ignored. Serves point probes (e.g. "
            "anchor-contention healing) that must not depend on the roster "
            "limit window."
        ),
    )


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
    session_filter = payload.get("session_id")
    if session_filter is not None:
        if not isinstance(session_filter, str) or not session_filter.strip():
            return _error(
                "payload_invalid",
                "session_id must be a non-empty string when present",
                jsonpath="$.payload.session_id",
            )
        row = _session_liveness_row(session_filter.strip())
        return HandlerOutcome(
            result_payload={
                "fields": list(SESSION_LIVENESS_FIELDS),
                "rows": [] if row is None else [row],
            },
            primary_success=True,
        )
    project = payload.get("project")
    liveness = payload.get("liveness")
    limit = payload.get("limit")
    per_project = payload.get("per_project", False)
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
    if not isinstance(per_project, bool):
        return _error(
            "payload_invalid",
            "per_project must be a boolean when present",
            jsonpath="$.payload.per_project",
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
            per_project=per_project,
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
