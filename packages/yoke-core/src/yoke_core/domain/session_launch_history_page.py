"""Cursor-paged launch reads that never hide a launch still needing attention.

The Session launches view answers two different questions from one table.
Launches that are still on their way to a session, or that stopped in a state
the operator can act on, must all be visible however old they are — hiding one
behind a page boundary hides the retry or reconcile it is waiting for. Finished
launches are history: interesting, unbounded, and safe to page.

So this module splits one criteria set across two reads. The operational set is
returned complete. Completed history is paged newest-first through an opaque
cursor keyed on ``(created_at, launch_id)``, which is stable while newer
launches arrive because it names a position rather than an offset.
"""

from __future__ import annotations

import base64
from typing import Any, Optional, Sequence

from yoke_core.domain.json_helper import dumps_compact, loads_text
from yoke_core.domain.project_identity import resolve_project_slug
from yoke_core.domain.session_launch_delivery_state import IN_FLIGHT_LAUNCH_STATES
from yoke_core.domain.session_launch_projection import compact_launch_records
from yoke_core.domain.session_launch_store import (
    LAUNCH_COLUMNS,
    marker,
    row_to_launch,
    value,
)
from yoke_core.domain.session_launch_types import LaunchRecord, SessionLaunchError


#: States the Session launches view offers a retry or a reconcile for. They are
#: terminal, but the operator still owes them a decision.
ACTIONABLE_LAUNCH_STATES = frozenset({"expired", "failed", "outcome_unknown"})
#: Unfinished plus actionable: the set that is always shown in full.
OPERATIONAL_LAUNCH_STATES = frozenset(IN_FLIGHT_LAUNCH_STATES | ACTIONABLE_LAUNCH_STATES)

DEFAULT_HISTORY_LIMIT = 50
MAX_HISTORY_LIMIT = 100


def encode_launch_cursor(created_at: str, launch_id: str) -> str:
    raw = dumps_compact({"created_at": created_at, "launch_id": launch_id})
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_launch_cursor(cursor: Optional[str]) -> Optional[tuple[str, str]]:
    """Return the cursor position, or refuse with the step that clears it."""
    if cursor is None:
        return None
    try:
        padding = "=" * (-len(cursor) % 4)
        payload = loads_text(
            base64.urlsafe_b64decode((cursor + padding).encode()).decode()
        )
        if not isinstance(payload, dict) or set(payload) != {
            "created_at",
            "launch_id",
        }:
            raise ValueError
        created_at = payload["created_at"]
        launch_id = payload["launch_id"]
        if not isinstance(created_at, str) or not created_at:
            raise ValueError
        if not isinstance(launch_id, str) or not launch_id:
            raise ValueError
        return created_at, launch_id
    except (TypeError, UnicodeError, ValueError):
        raise SessionLaunchError(
            "cursor_invalid",
            "the launch history cursor is unreadable; clear it and load the "
            "first history page again",
        ) from None


def _criteria(
    conn: Any,
    *,
    project_id: int,
    state: Optional[str],
    surface: Optional[str],
    machine: Optional[str],
) -> tuple[list[str], list[Any]]:
    p = marker(conn)
    clauses = [f"project_id = {p}"]
    params: list[Any] = [project_id]
    if state:
        clauses.append(f"state = {p}")
        params.append(state)
    if surface:
        clauses.append(f"(requested_surface = {p} OR selected_surface = {p})")
        params.extend([surface, surface])
    if machine:
        clauses.append(f"(requested_machine_id = {p} OR assigned_machine_id = {p})")
        params.extend([machine, machine])
    return clauses, params


def _state_set_clause(conn: Any, *, member: bool) -> tuple[str, list[Any]]:
    p = marker(conn)
    states = sorted(OPERATIONAL_LAUNCH_STATES)
    placeholders = ", ".join(p for _ in states)
    keyword = "IN" if member else "NOT IN"
    return f"state {keyword} ({placeholders})", list(states)


def _select(conn: Any, clauses: Sequence[str], params: Sequence[Any], order: str) -> list[LaunchRecord]:
    rows = conn.execute(
        f"SELECT {LAUNCH_COLUMNS} FROM session_launches "
        f"WHERE {' AND '.join(clauses)} {order}",
        tuple(params),
    ).fetchall()
    return [row_to_launch(row) for row in rows]


def _count(conn: Any, clauses: Sequence[str], params: Sequence[Any]) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS matched FROM session_launches "
        f"WHERE {' AND '.join(clauses)}",
        tuple(params),
    ).fetchone()
    return int(value(row, "matched", 0) or 0) if row is not None else 0


def read_launch_page(
    conn: Any,
    *,
    project_id: int,
    state: Optional[str] = None,
    surface: Optional[str] = None,
    machine: Optional[str] = None,
    limit: int = DEFAULT_HISTORY_LIMIT,
    cursor: Optional[str] = None,
) -> dict[str, Any]:
    """Read one page: the complete operational set plus a history window.

    Rows come back as compact list projections labelled with the project slug,
    which is what an all-project browser scope needs to merge several of these
    pages and still say where each row came from.

    Criteria are applied before both selections and before both counts, so a
    filtered view never reports a number it is not showing. Continuation
    requests carry completed history only — the caller already holds the
    operational rows from its first request, and re-sending them would make
    Load more duplicate what is on screen.
    """
    page_size = max(1, min(int(limit), MAX_HISTORY_LIMIT))
    base_clauses, base_params = _criteria(
        conn,
        project_id=project_id,
        state=state,
        surface=surface,
        machine=machine,
    )
    decoded = decode_launch_cursor(cursor)

    operational_clause, operational_params = _state_set_clause(conn, member=True)
    operational_where = [*base_clauses, operational_clause]
    operational_values = [*base_params, *operational_params]
    operational_count = _count(conn, operational_where, operational_values)
    operational = (
        []
        if decoded is not None
        else _select(
            conn,
            operational_where,
            operational_values,
            "ORDER BY created_at DESC, launch_id DESC",
        )
    )

    history_clause, history_params = _state_set_clause(conn, member=False)
    history_where = [*base_clauses, history_clause]
    history_values = [*base_params, *history_params]
    history_matched_count = _count(conn, history_where, history_values)
    paged_where = list(history_where)
    paged_values = list(history_values)
    if decoded is not None:
        created_at, launch_id = decoded
        p = marker(conn)
        paged_where.append(
            f"(created_at < {p} OR (created_at = {p} AND launch_id < {p}))"
        )
        paged_values.extend([created_at, created_at, launch_id])
    p = marker(conn)
    paged_values.append(page_size + 1)
    history = _select(
        conn,
        paged_where,
        paged_values,
        f"ORDER BY created_at DESC, launch_id DESC LIMIT {p}",
    )
    has_more = len(history) > page_size
    history = history[:page_size]
    next_cursor = (
        encode_launch_cursor(str(history[-1].created_at), str(history[-1].launch_id))
        if has_more and history
        else None
    )
    slug = resolve_project_slug(conn, project_id)
    return {
        "operational": compact_launch_records(operational, slug),
        "operational_count": operational_count,
        "history": compact_launch_records(history, slug),
        "history_matched_count": history_matched_count,
        "next_cursor": next_cursor,
    }


__all__ = [
    "ACTIONABLE_LAUNCH_STATES",
    "DEFAULT_HISTORY_LIMIT",
    "MAX_HISTORY_LIMIT",
    "OPERATIONAL_LAUNCH_STATES",
    "decode_launch_cursor",
    "encode_launch_cursor",
    "read_launch_page",
]
