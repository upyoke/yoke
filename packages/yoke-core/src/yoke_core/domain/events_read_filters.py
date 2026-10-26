"""Shared payload filters and actor authorization for event reads."""

from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple
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


def _where_from_payload(
    request: FunctionCallRequest,
    payload: Optional[Dict[str, Any]] = None,
) -> Tuple[str, List[Any], Optional[HandlerOutcome]]:
    """Translate payload filters into the shared events WHERE builder.

    The ``--item`` filter never rides the flag list: the dispatcher has
    already resolved ``target.public_ref`` server-side, so the resolved
    internal id is appended as a direct equality clause instead of
    re-parsing a public ref. ``payload`` overrides the request's own when a
    caller authorizes a filter itself and removes it from the flag list.
    """
    from yoke_core.domain.events_queries import _build_where
    from yoke_core.domain.actor_permissions import PermissionDenied
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.performance_query import authorized_predicate
    from yoke_core.domain.project_identity import resolve_project_id

    payload = request.payload or {} if payload is None else payload
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
        with connect() as conn:
            token = payload.get("project")
            projects = [resolve_project_id(conn, token)] if token else None
            predicate, scope_params = authorized_predicate(
                conn, request.actor.actor_id, projects
            )
        predicate = predicate.replace("e.project_id", "events.project_id")
        where = f"{where} AND ({predicate})" if where else f"WHERE ({predicate})"
        params = [*params, *scope_params]
    except PermissionDenied:
        return (
            "",
            [],
            HandlerOutcome(
                primary_success=False,
                error=FunctionError(
                    code="events_scope_denied",
                    message="Select a project where you hold events.read, or ask its admin for access.",
                ),
            ),
        )
    except ValueError as exc:
        return (
            "",
            [],
            HandlerOutcome(
                primary_success=False,
                error=FunctionError(
                    code="payload_invalid",
                    message=str(exc),
                    jsonpath="$.payload",
                ),
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
