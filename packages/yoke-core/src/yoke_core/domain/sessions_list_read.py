"""Read-only session roster with liveness and held-claims derivation.

The read behind ``sessions.list``: one row per harness session carrying
the attribution facts (actor id/kind plus the canonical display label),
what the session holds (its active work-claims and coordination leases,
typed targets rendered to display strings), how alive it is, and what
Yoke directed it to do (``execution_lane`` + ``mode``, both stored on
``harness_sessions``).

Liveness is derived server-side so no consumer re-encodes TTL numbers:

* ``ended`` — ``ended_at`` is set.
* ``stale`` — not ended, and the latest activity timestamp
  (``MAX(last_heartbeat, last_tool_call_at)``) is older than the
  executor-aware TTL from
  :func:`yoke_core.domain.session_staleness.activity_is_stale` — the
  same predicate the stale-session reclaim sweep uses.
* ``active`` — not ended and the activity timestamp is fresh.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from yoke_core.domain import db_helpers
from yoke_core.domain.actors import (
    ActorLabelAmbiguous,
    ActorLabelMissing,
    ActorNotFound,
)
from yoke_core.domain.actor_display import actor_display_name
from yoke_core.domain.project_identity import resolve_project_id
from yoke_core.domain.session_staleness import activity_is_stale
from yoke_core.domain.session_list_fields import SESSION_LIST_FIELDS
from yoke_core.domain.sessions_holdings_read import (
    active_claims_by_session,
    active_leases_by_session,
    claimed_blitz_worktree_ids_by_session,
)
from yoke_core.domain.sessions_list_query import build_sessions_query
from yoke_core.domain.sessions_queries_base import display_claim_item_id
from yoke_core.domain.session_presentation_read import session_presentation


LIVENESS_ACTIVE = "active"
LIVENESS_STALE = "stale"
LIVENESS_ENDED = "ended"
LIVENESS_STATES = (LIVENESS_ACTIVE, LIVENESS_STALE, LIVENESS_ENDED)

DEFAULT_SESSIONS_LIST_LIMIT = 100
MAX_SESSIONS_LIST_LIMIT = 500

#: Under the unscoped (``project=None``) roster read with ``per_project=True``,
#: the newest-N sessions kept PER PROJECT — each project, and the NULL-project
#: partition, gets its own slice — so a busy project cannot crowd a quiet one
#: out of the fetch window. Opt-in so the flat unscoped read (search, the full
#: roster view) keeps its universe-wide newest-N behavior.
PER_PROJECT_SESSIONS_LIST_CAP = 20


def _parse_timestamp(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _latest_activity(
    last_heartbeat: Any,
    last_tool_call_at: Any,
) -> Tuple[Optional[str], Optional[datetime]]:
    """Pick the later of the two activity stamps, keeping the raw string."""
    candidates = [
        (value, _parse_timestamp(value))
        for value in (last_heartbeat, last_tool_call_at)
    ]
    dated = [pair for pair in candidates if pair[1] is not None]
    if not dated:
        return None, None
    raw, parsed = max(dated, key=lambda pair: pair[1])
    return str(raw), parsed


def _actor_label(conn: Any, cache: Dict[int, str], actor_id: Any) -> Optional[str]:
    if actor_id is None:
        return None
    key = int(actor_id)
    if key not in cache:
        try:
            cache[key] = actor_display_name(conn, key)
        except (ActorNotFound, ActorLabelMissing, ActorLabelAmbiguous):
            cache[key] = f"actor {key}"
    return cache[key]


def list_sessions(
    *,
    project: Optional[str] = None,
    liveness: Optional[str] = None,
    limit: int = DEFAULT_SESSIONS_LIST_LIMIT,
    per_project: bool = False,
    session_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """List harness sessions, newest activity first.

    ``project`` filters on the session's own ``project_id`` binding
    (slug or id, resolved server-side). ``liveness`` filters to one of
    :data:`LIVENESS_STATES`; the ended/not-ended half of that split
    prunes in SQL, while the active/stale split classifies within the
    ``limit`` window (the TTL is executor-aware, so it cannot live in
    the WHERE clause).

    ``per_project`` only takes effect on the unscoped roster
    (``project=None``): the fetch window becomes each project's own
    newest-:data:`PER_PROJECT_SESSIONS_LIST_CAP` slice (NULL-project
    sessions form their own partition), so a busy project cannot crowd a
    quiet one out. The flat unscoped read is unchanged when it is off.

    ``session_id`` selects exactly one session through the same row renderer
    and enrichment pipeline. The point lookup bypasses both list limits while
    preserving the optional project and liveness filters.
    """
    if liveness is not None and liveness not in LIVENESS_STATES:
        raise ValueError(
            f"liveness must be one of {', '.join(LIVENESS_STATES)}; got {liveness!r}"
        )
    normalized_session_id = str(session_id or "").strip()
    if session_id is not None and not normalized_session_id:
        raise ValueError("session_id must be a non-empty string when present")
    bounded_limit = (
        1 if normalized_session_id else max(1, min(int(limit), MAX_SESSIONS_LIST_LIMIT))
    )
    windowed = per_project and not project and not normalized_session_id

    conn = db_helpers.connect()
    try:
        clauses: List[str] = []
        where_params: List[Any] = []
        if project:
            clauses.append("s.project_id = %s")
            where_params.append(resolve_project_id(conn, project))
        if normalized_session_id:
            clauses.append("s.session_id = %s")
            where_params.append(normalized_session_id)
        if liveness == LIVENESS_ENDED:
            clauses.append("s.ended_at IS NOT NULL")
        elif liveness in (LIVENESS_ACTIVE, LIVENESS_STALE):
            clauses.append("s.ended_at IS NULL")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

        # Timestamps are uniform ISO-8601 text, so lexicographic GREATEST
        # matches chronological order for the coarse fetch window; the
        # precise per-row classification below re-parses real datetimes. The
        # windowed shape gives each project (and the NULL-project partition)
        # its own newest-N slice so a busy project cannot crowd a quiet one out.
        query = build_sessions_query(where, windowed=windowed)
        if windowed:
            params = [*where_params, PER_PROJECT_SESSIONS_LIST_CAP, bounded_limit]
        else:
            params = [*where_params, bounded_limit]
        rows = conn.execute(query, tuple(params)).fetchall()

        claims_by_session, roles_by_session = active_claims_by_session(conn)
        leases_by_session = active_leases_by_session(conn, roles_by_session)
        blitz_lanes_by_session = claimed_blitz_worktree_ids_by_session(conn)
        label_cache: Dict[int, str] = {}
        result: List[Dict[str, Any]] = []
        for raw in rows:
            row = dict(raw)
            activity_at, _parsed = _latest_activity(
                row.get("last_heartbeat"),
                row.get("last_tool_call_at"),
            )
            if row.get("ended_at"):
                state = LIVENESS_ENDED
            elif activity_is_stale(
                activity_at,
                executor=row.get("executor"),
            ):
                state = LIVENESS_STALE
            else:
                state = LIVENESS_ACTIVE
            if liveness is not None and state != liveness:
                continue
            session_id = str(row["session_id"])
            current_item = row.get("current_item_id")
            current_item_display = (
                display_claim_item_id(str(current_item), conn) if current_item else None
            )
            claims = claims_by_session.get(session_id, [])
            item_claims = [
                claim
                for claim in claims
                if claim.get("target_kind") == "item"
                and claim.get("target") == current_item_display
            ]
            owns_current_item = bool(item_claims)
            current_item_num = int(current_item) if current_item is not None else None
            held_roles = [
                claim
                for claim in roles_by_session.get(session_id, [])
                if claim.get("item_id") == current_item_num
            ]
            task_roles = [
                claim.get("lane_role")
                for claim in held_roles
                if claim.get("target_kind") == "epic_task" and claim.get("lane_role")
            ]
            item_roles = [
                claim.get("lane_role")
                for claim in held_roles
                if claim.get("target_kind") == "item" and claim.get("lane_role")
            ]
            work_role = next(iter(task_roles or item_roles), None)
            if not work_role and current_item_display:
                work_role = "item" if owns_current_item else "attached"
            executor_surface = row.get("executor_surface")
            presentation = session_presentation(conn, row)
            result.append(
                {
                    "session_id": session_id,
                    "liveness": state,
                    "activity_at": activity_at,
                    "execution_lane": row.get("execution_lane"),
                    "lane_label": presentation["lane_label"],
                    "lane_glyph": presentation["lane_glyph"],
                    "mode": row.get("mode"),
                    "actor_id": row.get("actor_id"),
                    "actor_kind": row.get("actor_kind"),
                    "actor_label": _actor_label(
                        conn,
                        label_cache,
                        row.get("actor_id"),
                    ),
                    "project_id": row.get("project_id"),
                    "project": row.get("project"),
                    "executor": row.get("executor"),
                    "executor_surface": executor_surface,
                    "executor_mark": presentation["executor_mark"],
                    "executor_class_name": presentation["executor_class_name"],
                    "model": row.get("model"),
                    "workspace": row.get("workspace"),
                    "offered_at": row.get("offered_at"),
                    "ended_at": row.get("ended_at"),
                    "current_item": current_item_display,
                    "current_item_project_id": row.get(
                        "current_item_project_id",
                    ),
                    "current_item_project_sequence": row.get(
                        "current_item_project_sequence",
                    ),
                    "current_item_title": row.get("current_item_title"),
                    "current_item_workflow_id": row.get(
                        "current_item_workflow_id",
                    ),
                    "current_item_workflow_version_id": row.get(
                        "current_item_workflow_version_id",
                    ),
                    "work_role": work_role,
                    "owns_current_item": owns_current_item,
                    "claim_started_at": (
                        item_claims[0].get("claimed_at") if item_claims else None
                    ),
                    "claims": claims,
                    "coordination_leases": leases_by_session.get(session_id, []),
                    "claimed_blitz_worktree_ids": blitz_lanes_by_session.get(
                        session_id,
                        [],
                    ),
                }
            )
        return result
    finally:
        conn.close()


__all__ = [
    "DEFAULT_SESSIONS_LIST_LIMIT",
    "LIVENESS_ACTIVE",
    "LIVENESS_ENDED",
    "LIVENESS_STALE",
    "LIVENESS_STATES",
    "MAX_SESSIONS_LIST_LIMIT",
    "PER_PROJECT_SESSIONS_LIST_CAP",
    "SESSION_LIST_FIELDS",
    "list_sessions",
]
