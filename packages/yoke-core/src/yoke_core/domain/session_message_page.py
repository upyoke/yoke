"""Actionable-first, cursor-paged reads for the Fleet Messages view."""

from __future__ import annotations

from yoke_core.domain.db_helpers import instant_parameter

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from yoke_contracts.timestamps import parse_instant
from yoke_core.domain.session_message_cursor import (
    decode_message_cursor,
    encode_message_cursor,
)

from yoke_core.domain import db_backend
from yoke_core.domain.actor_message_recipients import ACTOR_KIND
from yoke_contracts.read_detail import DETAIL_FULL, DETAIL_SUMMARY
from yoke_core.domain.session_message_list_row import message_list_row
from yoke_core.domain.session_message_page_rows import page_summaries
from yoke_core.domain.session_message_queries import message_with_actor_context
from yoke_core.domain.session_message_reads import message_recipient_match_clause
from yoke_core.domain.session_message_receipt_expiry import OPEN_SESSION_STATES
from yoke_core.domain.session_message_types import (
    utc_now,
)
from yoke_core.domain.session_message_visibility import visible_clause
from yoke_core.domain.steering_message_recipients import (
    STATE_AWAITING_SEAT,
    STATE_DELIVERED,
    STEERING_KIND,
)


DEFAULT_SETTLED_LIMIT = 50
MAX_SETTLED_LIMIT = 500
OPEN_STEERING_STATES = (STATE_AWAITING_SEAT, STATE_DELIVERED)


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _project_clause(
    conn: Any, projects: list[int] | None
) -> tuple[str | None, list[Any]]:
    if projects is None:
        return None, []
    p = _p(conn)
    project_ids = sorted({int(project_id) for project_id in projects})
    actor_branch = (
        "(EXISTS (SELECT 1 FROM actor_message_recipients pa "
        f"WHERE pa.message_id=m.message_id AND pa.recipient_kind={p}) OR "
        "EXISTS (SELECT 1 FROM session_message_recipients po "
        "WHERE po.message_id=m.message_id AND po.org_id IS NOT NULL))"
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


def _actionable_clause(conn: Any, now: Any) -> tuple[str, list[Any]]:
    """A message needs attention while some recipient still owes an answer.

    Nothing owes an answer once the message itself has expired, whatever
    its receipt rows still say: reads never write expiry, and the relay
    cadence persists it later (see
    :mod:`yoke_core.domain.session_message_receipt_expiry`). Steering rows
    cannot carry an ``expired`` state at all, so the same message-level
    test covers them.
    """
    p = _p(conn)
    session_slots = ",".join(p for _ in OPEN_SESSION_STATES)
    steering_slots = ",".join(p for _ in OPEN_STEERING_STATES)
    return (
        f"(m.cancelled_at IS NULL AND m.expires_at>{p} AND (EXISTS (SELECT 1 "
        "FROM session_message_recipients ao WHERE ao.message_id=m.message_id "
        f"AND ao.state IN ({session_slots})) OR EXISTS (SELECT 1 FROM "
        "actor_message_recipients aa WHERE aa.message_id=m.message_id "
        f"AND aa.recipient_kind={p} AND aa.state='pending') OR EXISTS "
        "(SELECT 1 FROM actor_message_recipients ast WHERE "
        f"ast.message_id=m.message_id AND ast.recipient_kind={p} "
        f"AND ast.state IN ({steering_slots}))))",
        [
            now,
            *OPEN_SESSION_STATES,
            ACTOR_KIND,
            STEERING_KIND,
            *OPEN_STEERING_STATES,
        ],
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
) -> list[tuple[str, datetime]]:
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
    return [(str(row[0]), parse_instant(row[1])) for row in rows]


def _summaries(
    rows: dict[str, dict[str, Any]],
    ids: Sequence[tuple[str, datetime]],
    *,
    actor_id: int,
    caller_session_id: str | None,
    needs_attention: bool,
    detail: str,
) -> list[dict[str, Any]]:
    """Caller-relative rows in page order; ids were already visibility-filtered."""
    page: list[dict[str, Any]] = []
    for message_id, _created_at in ids:
        summary = message_with_actor_context(
            rows[message_id], actor_id=actor_id, session_id=caller_session_id
        )
        summary["needs_attention"] = needs_attention
        page.append(summary if detail == DETAIL_FULL else message_list_row(summary))
    return page


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
    detail: str = DETAIL_SUMMARY,
) -> dict[str, Any]:
    """Return every matching actionable message and one settled page.

    A fixed number of statements answers any page size: two counts, two id
    selections and the batched summary reads. Nothing here writes.
    """
    p = _p(conn)
    now = utc_now()
    bound_now = instant_parameter(conn, now)
    recipient_clause, recipient_params = message_recipient_match_clause(
        p, state=state, session_id=session_id, actor_id=actor_id, now=bound_now
    )
    visibility, visible_params = visible_clause(
        conn, actor_id=actor_id, caller_session_id=caller_session_id
    )
    clauses = [recipient_clause, visibility]
    params = [*recipient_params, *visible_params]
    project_clause, project_params = _project_clause(conn, projects)
    if project_clause:
        clauses.append(project_clause)
        params.extend(project_params)
    actionable_clause, actionable_params = _actionable_clause(conn, bound_now)
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
        settled_values.extend(
            [
                instant_parameter(conn, created_at),
                instant_parameter(conn, created_at),
                message_id,
            ]
        )
    page_size = max(1, min(int(limit), MAX_SETTLED_LIMIT))
    settled_ids = _select_ids(conn, settled_where, settled_values, limit=page_size + 1)
    has_more = len(settled_ids) > page_size
    settled_ids = settled_ids[:page_size]
    next_cursor = (
        encode_message_cursor(settled_ids[-1][1], settled_ids[-1][0])
        if has_more and settled_ids
        else None
    )
    rows = page_summaries(
        conn, [message_id for message_id, _ in (*actionable_ids, *settled_ids)], now=now
    )
    messages = [
        *_summaries(
            rows,
            actionable_ids,
            actor_id=actor_id,
            caller_session_id=caller_session_id,
            needs_attention=True,
            detail=detail,
        ),
        *_summaries(
            rows,
            settled_ids,
            actor_id=actor_id,
            caller_session_id=caller_session_id,
            needs_attention=False,
            detail=detail,
        ),
    ]
    return {
        "messages": messages,
        "count": len(messages),
        "actionable_count": actionable_count,
        "settled_loaded_count": len(settled_ids),
        "settled_matched_count": settled_matched_count,
        "next_cursor": next_cursor,
        "detail": detail,
    }


__all__ = [
    "DEFAULT_SETTLED_LIMIT",
    "decode_message_cursor",
    "encode_message_cursor",
    "read_message_page",
]
