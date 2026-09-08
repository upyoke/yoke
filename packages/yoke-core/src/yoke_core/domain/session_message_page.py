"""Actionable-first, cursor-paged reads for the Fleet Messages view."""

from __future__ import annotations

import base64
from collections.abc import Sequence
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.actor_message_recipients import ACTOR_KIND
from yoke_core.domain.actor_permissions import PERM_ITEMS_READ
from yoke_core.domain.actor_project_visibility import (
    actor_project_ids_with_permission,
)
from yoke_core.domain.json_helper import dumps_compact, loads_text
from yoke_core.domain.session_message_queries import (
    expire_message_receipts,
    message_visible,
    message_with_actor_context,
)
from yoke_core.domain.session_message_reads import (
    message_recipient_match_clause,
    message_summary,
)
from yoke_core.domain.session_message_types import SessionMessageError
from yoke_core.domain.steering_message_recipients import (
    STATE_AWAITING_SEAT,
    STATE_DELIVERED,
    STEERING_KIND,
)


DEFAULT_SETTLED_LIMIT = 50
MAX_SETTLED_LIMIT = 500
OPEN_SESSION_STATES = ("pending", "injected")
OPEN_STEERING_STATES = (STATE_AWAITING_SEAT, STATE_DELIVERED)


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def encode_message_cursor(created_at: str, message_id: str) -> str:
    raw = dumps_compact({"created_at": created_at, "message_id": message_id})
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_message_cursor(cursor: str | None) -> tuple[str, str] | None:
    if cursor is None:
        return None
    try:
        padding = "=" * (-len(cursor) % 4)
        payload = loads_text(
            base64.urlsafe_b64decode((cursor + padding).encode()).decode()
        )
        if not isinstance(payload, dict) or set(payload) != {
            "created_at",
            "message_id",
        }:
            raise ValueError
        created_at = payload["created_at"]
        message_id = payload["message_id"]
        if not isinstance(created_at, str) or not created_at:
            raise ValueError
        if not isinstance(message_id, str) or not message_id:
            raise ValueError
        return created_at, message_id
    except (TypeError, UnicodeError, ValueError):
        raise SessionMessageError(
            "cursor_invalid",
            "the settled-message cursor is unreadable; clear it and load the "
            "first Messages page again",
        ) from None


def _visible_clause(
    conn: Any,
    *,
    actor_id: int,
    caller_session_id: str | None,
) -> tuple[str, list[Any]]:
    p = _p(conn)
    branches = [
        f"m.sender_actor_id={p}",
        "EXISTS (SELECT 1 FROM actor_message_recipients va "
        f"WHERE va.message_id=m.message_id AND va.recipient_kind={p} "
        f"AND va.actor_id={p})",
    ]
    params: list[Any] = [actor_id, ACTOR_KIND, actor_id]
    if caller_session_id:
        branches.extend(
            [
                "EXISTS (SELECT 1 FROM session_message_recipients vs "
                f"WHERE vs.message_id=m.message_id AND vs.session_id={p})",
                "EXISTS (SELECT 1 FROM actor_message_recipients vst "
                f"WHERE vst.message_id=m.message_id AND vst.recipient_kind={p} "
                f"AND vst.seat_session_id={p})",
            ]
        )
        params.extend([caller_session_id, STEERING_KIND, caller_session_id])
    visible_projects = sorted(
        actor_project_ids_with_permission(conn, actor_id, PERM_ITEMS_READ) or []
    )
    if visible_projects:
        slots = ",".join(p for _ in visible_projects)
        branches.append(
            "(EXISTS (SELECT 1 FROM session_message_recipients vp "
            "WHERE vp.message_id=m.message_id) AND NOT EXISTS (SELECT 1 FROM "
            "session_message_recipients vx WHERE vx.message_id=m.message_id "
            f"AND vx.project_id NOT IN ({slots})))"
        )
        params.extend(visible_projects)
    return "(" + " OR ".join(branches) + ")", params


def _project_clause(
    conn: Any, projects: list[int] | None
) -> tuple[str | None, list[Any]]:
    if projects is None:
        return None, []
    p = _p(conn)
    project_ids = sorted({int(project_id) for project_id in projects})
    actor_branch = (
        "EXISTS (SELECT 1 FROM actor_message_recipients pa "
        f"WHERE pa.message_id=m.message_id AND pa.recipient_kind={p})"
    )
    if not project_ids:
        return actor_branch, [ACTOR_KIND]
    slots = ",".join(p for _ in project_ids)
    return (
        "(" + actor_branch + " OR EXISTS (SELECT 1 FROM "
        "session_message_recipients ps WHERE ps.message_id=m.message_id "
        f"AND ps.project_id IN ({slots})) OR EXISTS (SELECT 1 FROM "
        "actor_message_recipients pt WHERE pt.message_id=m.message_id "
        f"AND pt.recipient_kind={p} AND pt.project_id IN ({slots})))",
        [ACTOR_KIND, *project_ids, STEERING_KIND, *project_ids],
    )


def _actionable_clause(conn: Any) -> tuple[str, list[Any]]:
    p = _p(conn)
    session_slots = ",".join(p for _ in OPEN_SESSION_STATES)
    steering_slots = ",".join(p for _ in OPEN_STEERING_STATES)
    return (
        "(m.cancelled_at IS NULL AND (EXISTS (SELECT 1 FROM "
        "session_message_recipients ao WHERE ao.message_id=m.message_id "
        f"AND ao.state IN ({session_slots})) OR EXISTS (SELECT 1 FROM "
        "actor_message_recipients aa WHERE aa.message_id=m.message_id "
        f"AND aa.recipient_kind={p} AND aa.state='pending') OR EXISTS "
        "(SELECT 1 FROM actor_message_recipients ast WHERE "
        f"ast.message_id=m.message_id AND ast.recipient_kind={p} "
        f"AND ast.state IN ({steering_slots}))))",
        [*OPEN_SESSION_STATES, ACTOR_KIND, STEERING_KIND, *OPEN_STEERING_STATES],
    )


def _count(conn: Any, clauses: Sequence[str], params: Sequence[Any]) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS matched FROM session_messages m WHERE "
        + " AND ".join(clauses),
        tuple(params),
    ).fetchone()
    return int(row[0]) if row is not None else 0


def _select_ids(
    conn: Any,
    clauses: Sequence[str],
    params: Sequence[Any],
    *,
    limit: int | None = None,
) -> list[tuple[str, str]]:
    p = _p(conn)
    suffix = ""
    values = list(params)
    if limit is not None:
        suffix = f" LIMIT {p}"
        values.append(limit)
    rows = conn.execute(
        "SELECT m.message_id,m.created_at FROM session_messages m WHERE "
        + " AND ".join(clauses)
        + " ORDER BY m.created_at DESC,m.message_id DESC"
        + suffix,
        tuple(values),
    ).fetchall()
    return [(str(row[0]), str(row[1])) for row in rows]


def _summaries(
    conn: Any,
    ids: Sequence[tuple[str, str]],
    *,
    actor_id: int,
    caller_session_id: str | None,
    needs_attention: bool,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for message_id, _created_at in ids:
        summary = message_summary(conn, message_id)
        if not message_visible(
            conn,
            summary,
            actor_id=actor_id,
            session_id=caller_session_id,
        ):
            continue
        summary = message_with_actor_context(
            summary, actor_id=actor_id, session_id=caller_session_id
        )
        summary["needs_attention"] = needs_attention
        rows.append(summary)
    return rows


def read_message_page(
    conn: Any,
    *,
    actor_id: int,
    caller_session_id: str | None,
    state: str | None = None,
    session_id: str | None = None,
    projects: list[int] | None = None,
    limit: int = DEFAULT_SETTLED_LIMIT,
    cursor: str | None = None,
) -> dict[str, Any]:
    """Return every matching actionable message and one settled page."""
    expire_message_receipts(conn)
    p = _p(conn)
    recipient_clause, recipient_params = message_recipient_match_clause(
        p, state=state, session_id=session_id, actor_id=actor_id
    )
    visible_clause, visible_params = _visible_clause(
        conn, actor_id=actor_id, caller_session_id=caller_session_id
    )
    clauses = [recipient_clause, visible_clause]
    params = [*recipient_params, *visible_params]
    project_clause, project_params = _project_clause(conn, projects)
    if project_clause:
        clauses.append(project_clause)
        params.extend(project_params)
    actionable_clause, actionable_params = _actionable_clause(conn)
    actionable_where = [*clauses, actionable_clause]
    actionable_values = [*params, *actionable_params]
    actionable_count = _count(conn, actionable_where, actionable_values)
    decoded = decode_message_cursor(cursor)
    actionable_ids = (
        []
        if decoded is not None
        else _select_ids(conn, actionable_where, actionable_values)
    )

    settled_where = [*clauses, f"NOT {actionable_clause}"]
    settled_values = [*params, *actionable_params]
    settled_matched_count = _count(conn, settled_where, settled_values)
    if decoded is not None:
        created_at, message_id = decoded
        settled_where.append(
            f"(m.created_at < {p} OR (m.created_at = {p} AND m.message_id < {p}))"
        )
        settled_values.extend([created_at, created_at, message_id])
    page_size = max(1, min(int(limit), MAX_SETTLED_LIMIT))
    settled_ids = _select_ids(conn, settled_where, settled_values, limit=page_size + 1)
    has_more = len(settled_ids) > page_size
    settled_ids = settled_ids[:page_size]
    next_cursor = (
        encode_message_cursor(settled_ids[-1][1], settled_ids[-1][0])
        if has_more and settled_ids
        else None
    )
    messages = [
        *_summaries(
            conn,
            actionable_ids,
            actor_id=actor_id,
            caller_session_id=caller_session_id,
            needs_attention=True,
        ),
        *_summaries(
            conn,
            settled_ids,
            actor_id=actor_id,
            caller_session_id=caller_session_id,
            needs_attention=False,
        ),
    ]
    return {
        "messages": messages,
        "count": len(messages),
        "actionable_count": actionable_count,
        "settled_loaded_count": len(settled_ids),
        "settled_matched_count": settled_matched_count,
        "next_cursor": next_cursor,
    }


__all__ = [
    "DEFAULT_SETTLED_LIMIT",
    "decode_message_cursor",
    "encode_message_cursor",
    "read_message_page",
]
