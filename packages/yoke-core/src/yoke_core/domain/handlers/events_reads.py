"""Events read handlers: query, tail, count, anomalies.

One module owns every ``events.*`` read id. The filter grammar is NOT
re-implemented here — payload keys translate into the same flag list
:func:`yoke_core.domain.events_queries._build_where` parses for the
``db_router events`` operator-debug CLI, so both surfaces share one
WHERE builder (including relative ``--since``/``--until`` parsing and
the ``--current-episode`` fail-closed contract from
:mod:`yoke_core.domain.events_current_episode`).

All ids registered from this module carry ``claim_required_kind=None``
(reads never require an active claim) and ride ``PERM_EVENTS_READ``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_contracts.timestamps import temporal_wire
from yoke_core.domain.events_history_read import (
    EventsHistoryRequest,
    history_outcome,
)
from yoke_core.domain.handlers.event_presentation import present_event
from yoke_core.domain.events_read_filters import _where_from_payload




class EventsFilterRequest(BaseModel):
    """Shared filter surface — one payload key per `_build_where` flag."""

    event_name: Optional[str] = None
    item_id: Optional[int] = None
    session_id: Optional[str] = Field(
        default=None,
        description="Filter rows by events.session_id (not caller identity).",
    )
    source_type: Optional[str] = None
    event_kind: Optional[str] = None
    agent: Optional[str] = None
    service: Optional[str] = None
    actor_id: Optional[int] = None
    trace_id: Optional[str] = None
    project: Optional[str] = None
    tool_use_id: Optional[str] = None
    turn_id: Optional[str] = None
    hook_event_name: Optional[str] = None
    min_severity: Optional[str] = None
    since: Optional[str] = Field(
        default=None,
        description="ISO timestamp or relative form ('2 hours ago').",
    )
    until: Optional[str] = None
    current_episode: bool = Field(
        default=False,
        description="Bound to the current session episode; requires session_id.",
    )


class EventsQueryRequest(EventsFilterRequest):
    limit: int = Field(default=50, ge=1, le=1000)
    #: Selects the compact cursor-paged timeline shape. Absent keeps the
    #: unpaged raw projection every existing caller reads.
    history: Optional[EventsHistoryRequest] = None


class EventsQueryResponse(BaseModel):
    rows: List[Dict[str, Any]]
    #: Present only when ``current_episode`` hid same-filter rows.
    elided_prior_episode_rows: Optional[int] = None
    #: History shape only: the compact field allowlist and the cursor after
    #: this page (``None`` once the last match has been served).
    fields: Optional[List[str]] = None
    next_cursor: Optional[str] = None


class EventsTailRequest(BaseModel):
    limit: int = Field(default=20, ge=1, le=1000)
    project: Optional[str] = Field(
        default=None,
        description="Keep only this project's events (slug or id).",
    )


class EventsTailResponse(BaseModel):
    rows: List[Dict[str, Any]]
    #: Echo of the applied project filter, so a client can tell a filtered
    #: tail from one served by a build that ignored the filter.
    project: Optional[str] = None


class EventsCountRequest(EventsFilterRequest):
    pass


class EventsCountResponse(BaseModel):
    count: int


class EventsAnomaliesRequest(EventsFilterRequest):
    limit: int = Field(default=200, ge=1, le=1000)


class EventsAnomaliesResponse(BaseModel):
    rows: List[Dict[str, Any]]


def _validated_limit(
    payload: Dict[str, Any], default: int
) -> Tuple[Optional[int], Optional[HandlerOutcome]]:
    raw = payload.get("limit")
    if raw is None or raw == "":
        raw = default
    try:
        limit = int(raw)
    except (TypeError, ValueError):
        return None, HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="payload_invalid",
                message="limit must be an int 1..1000",
                jsonpath="$.payload.limit",
            ),
        )
    if limit < 1 or limit > 1000:
        return None, HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="payload_invalid",
                message="limit out of bounds (1..1000)",
                jsonpath="$.payload.limit",
            ),
        )
    return limit, None




def _select_rows(where: str, params: List[Any], limit: int) -> List[Dict[str, Any]]:
    """Newest-first typed projection plus readable presentation facts."""
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.events_history_read import presentation_facts
    from yoke_core.domain.events_select import (
        _EVT_SELECT_COLS,
        EVT_COLUMN_NAMES,
    )

    conn = connect()
    try:
        raw_rows = conn.execute(
            f"SELECT {_EVT_SELECT_COLS}, envelope FROM events {where} "
            f"ORDER BY created_at DESC, id DESC LIMIT %s",
            (*params, limit),
        ).fetchall()
        names = (*EVT_COLUMN_NAMES, "envelope")
        rows = [
            {
                name: ("" if value is None else str(temporal_wire(value)))
                for name, value in zip(names, tuple(row))
            }
            for row in raw_rows
        ]
        item_facts, actor_names = presentation_facts(conn, rows)
    finally:
        conn.close()
    return [present_event(row, item_facts, actor_names) for row in rows]


def handle_events_query(request: FunctionCallRequest) -> HandlerOutcome:
    if (request.payload or {}).get("history") is not None:
        return history_outcome(request, _where_from_payload)
    limit, limit_error = _validated_limit(request.payload or {}, default=50)
    if limit_error is not None:
        return limit_error
    where, params, where_error = _where_from_payload(request)
    if where_error is not None:
        return where_error
    from yoke_core.domain.events_current_episode import note_elided_prior_episodes

    result: Dict[str, Any] = {"rows": _select_rows(where, params, limit)}
    note_elided_prior_episodes(request.payload or {}, where, params, result)
    return HandlerOutcome(result_payload=result, primary_success=True)


def handle_events_tail(request: FunctionCallRequest) -> HandlerOutcome:
    limit, limit_error = _validated_limit(request.payload or {}, default=20)
    if limit_error is not None:
        return limit_error
    project = (request.payload or {}).get("project") or None
    where, params, where_error = _where_from_payload(
        request, {"project": project} if project else {}
    )
    if where_error is not None:
        return where_error
    return HandlerOutcome(
        result_payload={
            "rows": _select_rows(where, params, limit),
            "project": None if project is None else str(project),
        },
        primary_success=True,
    )


def handle_events_count(request: FunctionCallRequest) -> HandlerOutcome:
    where, params, where_error = _where_from_payload(request)
    if where_error is not None:
        return where_error
    from yoke_core.domain.db_helpers import connect

    conn = connect()
    try:
        row = conn.execute(
            f"SELECT COUNT(*) FROM events {where}",
            tuple(params),
        ).fetchone()
    finally:
        conn.close()
    return HandlerOutcome(
        result_payload={"count": int(row[0] if row else 0)},
        primary_success=True,
    )


def handle_events_anomalies(request: FunctionCallRequest) -> HandlerOutcome:
    limit, limit_error = _validated_limit(request.payload or {}, default=200)
    if limit_error is not None:
        return limit_error
    where, params, where_error = _where_from_payload(request)
    if where_error is not None:
        return where_error
    extra = "anomaly_flags IS NOT NULL AND anomaly_flags <> ''"
    where = f"{where} AND {extra}" if where else f"WHERE {extra}"
    return HandlerOutcome(
        result_payload={"rows": _select_rows(where, params, limit)},
        primary_success=True,
    )


__all__ = [
    "EventsQueryRequest",
    "EventsQueryResponse",
    "handle_events_query",
    "EventsTailRequest",
    "EventsTailResponse",
    "handle_events_tail",
    "EventsCountRequest",
    "EventsCountResponse",
    "handle_events_count",
    "EventsAnomaliesRequest",
    "EventsAnomaliesResponse",
    "handle_events_anomalies",
]
