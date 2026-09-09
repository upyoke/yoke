"""Compact, cursor-paged reads for the Events diagnostic timeline.

The timeline is a retained history, not a window: the newest fifty rows of a
busy universe cover seconds. This module reads one deterministically ordered
page at a time behind an opaque cursor, and returns only the facts the
timeline renders. The stored envelope is read so category, context, and
target can be derived server-side, then dropped rather than serialized —
shipping every envelope to a list that displays none of them was the entire
weight of the previous read.

The unpaged ``events.query.run`` projection is unchanged; only a request
carrying ``history`` selects this shape.
"""

from __future__ import annotations

import base64
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_core.domain.handlers.event_presentation import present_event
from yoke_core.domain.json_helper import dumps_compact, loads_text


DEFAULT_HISTORY_LIMIT = 50
MAX_HISTORY_LIMIT = 100

#: Exactly the facts an entry renders. Anything absent here never reaches
#: the browser, so a new stored column cannot silently start riding along.
HISTORY_FIELDS = (
    "created_at",
    "event_name",
    "category",
    "severity",
    "context_label",
    "target_kind",
    "target_label",
    "target_id",
    "target_project_id",
    "source_label",
    "source_type",
    "project",
)

#: Stored columns the derivation above needs, plus the keyset ordering key.
#: Deliberately narrower than ``_EVT_SELECT_COLS``: the fields a timeline
#: entry never shows are not fetched at all.
_HISTORY_SELECT_COLS = (
    "id, created_at, event_name, severity, event_kind, event_type, "
    "event_outcome, COALESCE(source_type,'') AS source_type, "
    "COALESCE(session_id,'') AS session_id, "
    "COALESCE(item_id,'') AS item_id, "
    "COALESCE(CAST(actor_id AS TEXT),'') AS actor_id, "
    "COALESCE(agent,'') AS agent, COALESCE(service,'') AS service, "
    "COALESCE((SELECT p.slug FROM projects p WHERE p.id = events.project_id), '') "
    "AS project, envelope"
)


class EventsHistoryRequest(BaseModel):
    """Paging inputs. Every filter rides the shared ``events.*`` payload."""

    model_config = ConfigDict(extra="forbid")
    limit: int = Field(default=DEFAULT_HISTORY_LIMIT, ge=1, le=MAX_HISTORY_LIMIT)
    cursor: Optional[str] = None


def presentation_facts(
    conn: Any,
    rows: Sequence[Dict[str, Any]],
) -> Tuple[Dict[int, Dict[str, Any]], Dict[int, str]]:
    """Resolve the item refs and actor labels a page of events points at."""
    from yoke_contracts.public_ref import format_item_ref

    item_ids = sorted(
        {int(row["item_id"]) for row in rows if str(row.get("item_id") or "").isdigit()}
    )
    item_facts: Dict[int, Dict[str, Any]] = {}
    if item_ids:
        markers = ", ".join("%s" for _ in item_ids)
        facts = conn.execute(
            "SELECT i.id, i.project_id, i.project_sequence, p.slug, "
            "p.public_item_prefix "
            "FROM items i JOIN projects p ON p.id = i.project_id "
            f"WHERE i.id IN ({markers})",
            tuple(item_ids),
        ).fetchall()
        for fact in facts:
            item_id = int(fact["id"])
            item_facts[item_id] = {
                "project_id": int(fact["project_id"]),
                "ref": format_item_ref(
                    str(fact["slug"]),
                    str(fact["public_item_prefix"] or ""),
                    int(fact["project_sequence"]),
                ),
            }
    actor_ids = sorted(
        {
            int(row["actor_id"])
            for row in rows
            if str(row.get("actor_id") or "").isdigit()
        }
    )
    actor_labels: Dict[int, str] = {}
    if actor_ids:
        markers = ", ".join("%s" for _ in actor_ids)
        actors = conn.execute(
            "SELECT a.id, COALESCE(NULLIF(a.name, ''), a.system_component, "
            "'actor ' || CAST(a.id AS TEXT)) AS label "
            f"FROM actors a WHERE a.id IN ({markers})",
            tuple(actor_ids),
        ).fetchall()
        actor_labels = {int(actor["id"]): str(actor["label"]) for actor in actors}
    return item_facts, actor_labels


def encode_cursor(created_at: str, event_id: int) -> str:
    raw = dumps_compact({"created_at": created_at, "id": int(event_id)})
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(value: Optional[str]) -> Optional[Tuple[str, int]]:
    """Return the decoded keyset position, or raise a named refusal."""
    if value is None or value == "":
        return None
    try:
        padding = "=" * (-len(value) % 4)
        decoded = base64.urlsafe_b64decode((value + padding).encode()).decode()
        payload = loads_text(decoded)
        if set(payload) != {"created_at", "id"}:  # type: ignore[arg-type]
            raise ValueError
        created_at = payload["created_at"]  # type: ignore[index]
        event_id = payload["id"]  # type: ignore[index]
        if not isinstance(created_at, str) or not created_at:
            raise ValueError
        return created_at, int(event_id)
    except (KeyError, TypeError, UnicodeError, ValueError):
        raise ValueError(
            "history.cursor is invalid; clear it and reload the first page"
        ) from None


def project_scope_clause(
    conn: Any,
    actor_id: Any,
    project: Optional[str],
) -> Tuple[str, List[Any]]:
    """Return the authorized project predicate for one history request.

    A criterion that names no project the caller can read is refused by name.
    Falling through to an unscoped read would answer a wider question than
    the operator asked, using rows they may not be allowed to see.
    """
    from yoke_core.domain.actor_project_visibility import (
        actor_visible_project_ids,
        numeric_actor_id,
    )
    from yoke_core.domain.project_identity import resolve_project

    visible = actor_visible_project_ids(conn, numeric_actor_id(actor_id))
    criterion = str(project or "").strip()
    if criterion:
        identity = resolve_project(
            conn,
            criterion,
            required=False,
            visible_project_ids=visible,
        )
        if identity is None:
            raise ValueError(
                f"project {criterion!r} is not a project you can read; "
                "choose a visible project and reload the first page"
            )
        return "project_id = %s", [identity.id]
    if visible is None:
        return "", []
    if not visible:
        return "1 = 0", []
    ids = sorted(visible)
    return f"project_id IN ({', '.join('%s' for _ in ids)})", list(ids)


def _compact(decorated: Dict[str, Any]) -> Dict[str, Any]:
    return {field: decorated.get(field) for field in HISTORY_FIELDS}


def read_event_history(
    conn: Any,
    *,
    where: str,
    params: Sequence[Any],
    limit: int,
    cursor: Optional[str],
) -> Dict[str, Any]:
    """Return one compact page, newest first, and the cursor after it.

    Filters are already in ``where``: they narrow the rows the keyset walks,
    so a filtered page is the newest matches rather than the matches inside
    an unfiltered page.
    """
    clause = where
    query_params = list(params)
    position = decode_cursor(cursor)
    if position is not None:
        created_at, event_id = position
        keyset = "(created_at < %s OR (created_at = %s AND id < %s))"
        clause = f"{clause} AND {keyset}" if clause else f"WHERE {keyset}"
        query_params.extend([created_at, created_at, event_id])
    raw_rows = conn.execute(
        f"SELECT {_HISTORY_SELECT_COLS} FROM events {clause} "
        "ORDER BY created_at DESC, id DESC LIMIT %s",
        (*query_params, limit + 1),
    ).fetchall()
    rows = [
        {
            name: ("" if value is None else str(value))
            for name, value in dict(raw).items()
        }
        for raw in raw_rows
    ]
    has_more = len(rows) > limit
    page = rows[:limit]
    item_facts, actor_labels = presentation_facts(conn, page)
    compact = [_compact(present_event(row, item_facts, actor_labels)) for row in page]
    next_cursor = None
    if has_more and page:
        last = page[-1]
        next_cursor = encode_cursor(str(last["created_at"]), int(last["id"]))
    return {
        "fields": list(HISTORY_FIELDS),
        "rows": compact,
        "next_cursor": next_cursor,
    }


def _refused(code: str, message: str, jsonpath: str) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message, jsonpath=jsonpath),
    )


def history_outcome(
    request: FunctionCallRequest,
    where_from_payload: Callable[..., Tuple[str, List[Any], Optional[HandlerOutcome]]],
) -> HandlerOutcome:
    """Serve the paged compact shape for a request carrying ``history``.

    ``where_from_payload`` is the shared events filter translation, passed in
    rather than imported so this module stays a leaf of the handler module
    that owns the grammar.
    """
    from yoke_core.domain.db_helpers import connect

    payload = dict(request.payload or {})
    try:
        history = EventsHistoryRequest.model_validate(payload.get("history"))
    except ValidationError as exc:
        issue = exc.errors()[0]
        path = ".".join(str(part) for part in issue.get("loc", ()))
        return _refused(
            "payload_invalid",
            f"history request invalid: {issue.get('msg')}; "
            "correct it and reload the first page",
            f"$.payload.history{'.' + path if path else ''}",
        )
    # The project criterion is authorized here instead of riding the shared
    # filter grammar, which resolves any existing project without asking
    # whether this caller may read it.
    project = payload.pop("project", None)
    where, params, where_error = where_from_payload(request, payload)
    if where_error is not None:
        return where_error
    conn = connect()
    try:
        try:
            clause, clause_params = project_scope_clause(
                conn,
                request.actor.actor_id if request.actor else None,
                project,
            )
        except ValueError as exc:
            return _refused("permission_denied", str(exc), "$.payload.project")
        if clause:
            where = f"{where} AND {clause}" if where else f"WHERE {clause}"
            params = [*params, *clause_params]
        try:
            result = read_event_history(
                conn,
                where=where,
                params=params,
                limit=history.limit,
                cursor=history.cursor,
            )
        except ValueError as exc:
            return _refused("payload_invalid", str(exc), "$.payload.history.cursor")
    finally:
        conn.close()
    return HandlerOutcome(result_payload=result, primary_success=True)


__all__ = [
    "DEFAULT_HISTORY_LIMIT",
    "EventsHistoryRequest",
    "HISTORY_FIELDS",
    "MAX_HISTORY_LIMIT",
    "decode_cursor",
    "encode_cursor",
    "history_outcome",
    "presentation_facts",
    "project_scope_clause",
    "read_event_history",
]
