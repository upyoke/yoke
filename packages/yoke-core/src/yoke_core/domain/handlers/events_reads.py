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


# Payload key -> events filter flag. Keys mirror the ``events`` table
# columns; the flag strings are the canonical `_build_where` grammar.
_EQUALITY_FILTER_FLAGS: Dict[str, str] = {
    "event_name": "--event-name",
    "session_id": "--session-id",
    "source_type": "--source-type",
    "event_kind": "--event-kind",
    "agent": "--agent",
    "service": "--service",
    "actor_id": "--actor-id",
    "trace_id": "--trace-id",
    "project": "--project",
    "tool_use_id": "--tool-use-id",
    "turn_id": "--turn-id",
    "hook_event_name": "--hook-event-name",
}


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


class EventsQueryResponse(BaseModel):
    rows: List[Dict[str, Any]]


class EventsTailRequest(BaseModel):
    limit: int = Field(default=20, ge=1, le=1000)


class EventsTailResponse(BaseModel):
    rows: List[Dict[str, Any]]


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
                code="payload_invalid", message="limit must be an int 1..1000",
                jsonpath="$.payload.limit",
            ),
        )
    if limit < 1 or limit > 1000:
        return None, HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="payload_invalid", message="limit out of bounds (1..1000)",
                jsonpath="$.payload.limit",
            ),
        )
    return limit, None


def _where_from_payload(
    request: FunctionCallRequest,
) -> Tuple[str, List[Any], Optional[HandlerOutcome]]:
    """Translate payload filters into the shared events WHERE builder.

    The ``--item`` filter never rides the flag list: the dispatcher has
    already resolved ``target.item_id`` server-side, so the resolved
    internal id is appended as a direct equality clause instead of
    re-parsing a public ref.
    """
    from yoke_core.domain.events_queries import _build_where

    payload = request.payload or {}
    args: List[str] = []
    for key, flag in _EQUALITY_FILTER_FLAGS.items():
        value = payload.get(key)
        if value is None or str(value) == "":
            continue
        args.extend([flag, str(value)])
    for key, flag in (
        ("min_severity", "--min-severity"),
        ("since", "--since"),
        ("until", "--until"),
    ):
        value = payload.get(key)
        if value:
            args.extend([flag, str(value)])
    if payload.get("current_episode"):
        args.append("--current-episode")
    try:
        where, params = _build_where(args)
    except ValueError as exc:
        return "", [], HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="payload_invalid", message=str(exc),
                jsonpath="$.payload",
            ),
        )

    item_id = payload.get("item_id")
    if (
        item_id is None
        and request.target.kind == "item"
        and request.target.item_id is not None
    ):
        # Relay shape: the --item filter rides the envelope target as a
        # raw ref; the dispatcher resolved it into target.item_id.
        item_id = int(request.target.item_id)
    if item_id is not None:
        clause = "item_id = %s"
        where = f"{where} AND {clause}" if where else f"WHERE {clause}"
        params = [*params, str(item_id)]
    return where, list(params), None


def _select_rows(
    where: str, params: List[Any], limit: int
) -> List[Dict[str, Any]]:
    """Newest-first typed projection over the canonical 24-column set."""
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.events_select import (
        _EVT_SELECT_COLS,
        EVT_COLUMN_NAMES,
    )

    conn = connect()
    try:
        rows = conn.execute(
            f"SELECT {_EVT_SELECT_COLS}, envelope FROM events {where} "
            f"ORDER BY created_at DESC, id DESC LIMIT %s",
            (*params, limit),
        ).fetchall()
    finally:
        conn.close()
    names = (*EVT_COLUMN_NAMES, "envelope")
    return [
        {name: ("" if value is None else str(value))
         for name, value in zip(names, tuple(row))}
        for row in rows
    ]


def handle_events_query(request: FunctionCallRequest) -> HandlerOutcome:
    limit, limit_error = _validated_limit(request.payload or {}, default=50)
    if limit_error is not None:
        return limit_error
    where, params, where_error = _where_from_payload(request)
    if where_error is not None:
        return where_error
    return HandlerOutcome(
        result_payload={"rows": _select_rows(where, params, limit)},
        primary_success=True,
    )


def handle_events_tail(request: FunctionCallRequest) -> HandlerOutcome:
    limit, limit_error = _validated_limit(request.payload or {}, default=20)
    if limit_error is not None:
        return limit_error
    return HandlerOutcome(
        result_payload={"rows": _select_rows("", [], limit)},
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
            f"SELECT COUNT(*) FROM events {where}", tuple(params),
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
    "EventsQueryRequest", "EventsQueryResponse", "handle_events_query",
    "EventsTailRequest", "EventsTailResponse", "handle_events_tail",
    "EventsCountRequest", "EventsCountResponse", "handle_events_count",
    "EventsAnomaliesRequest", "EventsAnomaliesResponse",
    "handle_events_anomalies",
]
