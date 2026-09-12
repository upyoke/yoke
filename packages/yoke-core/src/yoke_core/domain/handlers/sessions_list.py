"""``sessions.list`` read handler for live rosters and ended history."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class SessionsHistoryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    limit: int = Field(default=50, ge=1, le=100)
    cursor: Optional[str] = None
    search: str = ""
    projects: List[str] = Field(default_factory=list)
    harnesses: List[str] = Field(default_factory=list)
    machines: List[str] = Field(default_factory=list)


class SessionsListRequest(BaseModel):
    project: Optional[str] = None
    projects: List[str] = Field(default_factory=list)
    liveness: Optional[str] = None
    ended_cause: Optional[str] = None
    limit: Optional[int] = None
    per_project: bool = False
    open: bool = False
    session_id: Optional[str] = None
    history: Optional[SessionsHistoryRequest] = None
    usage_last_24h: bool = False


class SessionsListResponse(BaseModel):
    fields: List[str]
    rows: List[Dict[str, Any]]


#: Payload keys incompatible with every mutually-exclusive read mode
#: (``history``, ``usage_last_24h``) besides the mode's own scoping keys.
_LIVE_ROSTER_KEYS = ("liveness", "ended_cause", "open", "session_id", "per_project")


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


def _incompatible_keys(payload: Dict[str, Any], *extra: str) -> List[str]:
    return [
        key
        for key in (*_LIVE_ROSTER_KEYS, *extra)
        if payload.get(key) not in (None, False, "", [])
    ]


def _resolve_project_ids(
    conn: Any, project_refs: Sequence[str], visible: Optional[set[int]]
) -> Optional[set[int]]:
    """Named refs resolved against visibility, or ``visible`` unscoped when
    none are named. An unresolvable ref yields the empty set (matches
    nothing) rather than silently widening back to every visible project."""
    from yoke_core.domain.project_identity import resolve_project

    if not project_refs:
        return visible
    project_ids: set[int] = set()
    for project in project_refs:
        ident = resolve_project(
            conn, project, required=False, visible_project_ids=visible
        )
        if ident is None:
            return set()
        project_ids.add(ident.id)
    return project_ids


def _history_error(exc: ValidationError) -> HandlerOutcome:
    issue = exc.errors()[0]
    path = ".".join(str(part) for part in issue.get("loc", ()))
    return _error(
        "payload_invalid",
        f"history request invalid: {issue.get('msg')}; clear the cursor and reload the first history page",
        jsonpath=f"$.payload.history{'.' + path if path else ''}",
    )


def _history_result(
    request: FunctionCallRequest,
    history: SessionsHistoryRequest,
) -> HandlerOutcome:
    from yoke_core.domain import db_helpers
    from yoke_core.domain.actor_project_visibility import (
        actor_visible_project_ids,
        numeric_actor_id,
    )
    from yoke_core.domain.sessions_history_read import read_ended_session_history

    conn = db_helpers.connect()
    try:
        actor = request.actor.actor_id if request.actor else None
        visible = actor_visible_project_ids(conn, numeric_actor_id(actor))
        project_ids = _resolve_project_ids(conn, history.projects, visible)
        result = read_ended_session_history(
            conn,
            project_ids=project_ids,
            search=history.search,
            harnesses=history.harnesses,
            machines=history.machines,
            limit=history.limit,
            cursor=history.cursor,
        )
    except ValueError as exc:
        return _error(
            "payload_invalid",
            str(exc),
            jsonpath="$.payload.history.cursor",
        )
    finally:
        conn.close()
    return HandlerOutcome(result_payload=result, primary_success=True)


def _recent_usage_result(
    request: FunctionCallRequest, project_refs: List[str]
) -> HandlerOutcome:
    from yoke_core.domain import db_helpers
    from yoke_core.domain.actor_project_visibility import (
        actor_visible_project_ids,
        numeric_actor_id,
    )
    from yoke_core.domain.sessions_history_read import (
        read_recent_session_usage_by_machine,
    )

    conn = db_helpers.connect()
    try:
        actor = request.actor.actor_id if request.actor else None
        visible = actor_visible_project_ids(conn, numeric_actor_id(actor))
        project_ids = _resolve_project_ids(conn, project_refs, visible)
        result = read_recent_session_usage_by_machine(conn, project_ids=project_ids)
    finally:
        conn.close()
    return HandlerOutcome(result_payload=result, primary_success=True)


def _open_rows(
    request: FunctionCallRequest,
    project_refs: List[str],
    limit: int,
) -> List[Dict[str, Any]]:
    from yoke_core.domain import db_helpers
    from yoke_core.domain.actor_project_visibility import (
        actor_visible_project_ids,
        numeric_actor_id,
    )
    from yoke_core.domain.sessions_list_read import list_sessions

    conn = db_helpers.connect()
    try:
        actor = request.actor.actor_id if request.actor else None
        visible = actor_visible_project_ids(conn, numeric_actor_id(actor))
        project_ids = _resolve_project_ids(conn, project_refs, visible)
    finally:
        conn.close()
    if project_ids is None:
        return list_sessions(open=True, limit=limit)
    # A session's live steering claim can name a project other than its own
    # home project, so the same session now legitimately matches more than
    # one project's per-project fetch below; keep its first appearance and
    # drop the repeat rather than showing one session twice in the roster.
    by_session_id: Dict[str, Dict[str, Any]] = {}
    for project_id in sorted(project_ids):
        for row in list_sessions(project=str(project_id), open=True, limit=limit):
            by_session_id.setdefault(str(row.get("session_id") or ""), row)
    return list(by_session_id.values())


def handle_sessions_list(request: FunctionCallRequest) -> HandlerOutcome:
    if request.target.kind != "global":
        return _error(
            "target_invalid",
            "sessions.list requires target.kind='global'",
            jsonpath="$.target.kind",
        )
    payload = request.payload or {}
    if payload.get("history") is not None:
        incompatible = _incompatible_keys(
            payload, "project", "projects", "usage_last_24h"
        )
        if incompatible:
            return _error(
                "payload_invalid",
                "history cannot combine with live-roster inputs: "
                + ", ".join(incompatible)
                + "; remove them and reload the first history page",
                jsonpath="$.payload.history",
            )
        try:
            history = SessionsHistoryRequest.model_validate(payload["history"])
        except ValidationError as exc:
            return _history_error(exc)
        return _history_result(request, history)
    usage_last_24h = payload.get("usage_last_24h", False)
    if not isinstance(usage_last_24h, bool):
        return _error(
            "payload_invalid",
            "usage_last_24h must be a boolean when present",
            jsonpath="$.payload.usage_last_24h",
        )
    if usage_last_24h:
        incompatible = _incompatible_keys(payload, "limit", "history", "project")
        if incompatible:
            return _error(
                "payload_invalid",
                "usage_last_24h cannot combine with other sessions.list inputs: "
                + ", ".join(incompatible),
                jsonpath="$.payload.usage_last_24h",
            )
        usage_projects = payload.get("projects", [])
        if not isinstance(usage_projects, list) or any(
            not isinstance(value, str) or not value.strip()
            for value in usage_projects
        ):
            return _error(
                "payload_invalid",
                "projects must be a list of non-empty strings when present",
                jsonpath="$.payload.projects",
            )
        return _recent_usage_result(request, usage_projects)
    session_filter = payload.get("session_id")
    if session_filter is not None and (
        not isinstance(session_filter, str) or not session_filter.strip()
    ):
        return _error(
            "payload_invalid",
            "session_id must be a non-empty string when present",
            jsonpath="$.payload.session_id",
        )
    project = payload.get("project")
    projects = payload.get("projects", [])
    liveness = payload.get("liveness")
    ended_cause = payload.get("ended_cause")
    limit = payload.get("limit")
    per_project = payload.get("per_project", False)
    open_only = payload.get("open", False)
    for key, value in (
        ("project", project),
        ("liveness", liveness),
        ("ended_cause", ended_cause),
    ):
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
    if not isinstance(open_only, bool):
        return _error(
            "payload_invalid",
            "open must be a boolean when present",
            jsonpath="$.payload.open",
        )
    if not isinstance(projects, list) or any(
        not isinstance(value, str) or not value.strip() for value in projects
    ):
        return _error(
            "payload_invalid",
            "projects must be a list of non-empty strings when present",
            jsonpath="$.payload.projects",
        )
    if projects and (not open_only or project is not None):
        return _error(
            "payload_invalid",
            "projects requires open=true and cannot combine with project",
            jsonpath="$.payload.projects",
        )
    if not isinstance(per_project, bool):
        return _error(
            "payload_invalid",
            "per_project must be a boolean when present",
            jsonpath="$.payload.per_project",
        )
    from yoke_core.domain.sessions_list_read import (
        DEFAULT_SESSIONS_LIST_LIMIT,
        MAX_SESSIONS_LIST_LIMIT,
        list_sessions,
    )

    try:
        default_limit = (
            MAX_SESSIONS_LIST_LIMIT if open_only else DEFAULT_SESSIONS_LIST_LIMIT
        )
        effective_limit = limit if limit is not None else default_limit
        if open_only:
            rows = _open_rows(
                request, projects or ([project] if project else []), effective_limit
            )
        else:
            rows = list_sessions(
                project=project,
                liveness=liveness,
                ended_cause=ended_cause,
                limit=effective_limit,
                per_project=per_project,
                session_id=session_filter.strip()
                if session_filter is not None
                else None,
            )
    except ValueError as exc:
        return _error(
            "payload_invalid",
            str(exc),
            jsonpath=(
                "$.payload.ended_cause"
                if "ended_cause" in str(exc)
                else "$.payload.liveness"
            ),
        )
    except LookupError as exc:
        return _error(
            "not_found",
            str(exc),
            jsonpath="$.payload.project",
        )
    from yoke_core.domain.session_control_roster import session_control_roster_result

    return HandlerOutcome(
        result_payload=session_control_roster_result(rows),
        primary_success=True,
    )
