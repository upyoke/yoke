"""Read-only session roster with liveness and held-claims derivation.

The read behind ``sessions.list``: one row per harness session carrying
the attribution facts (actor id/kind plus the canonical display label),
what the session holds (its current and previous typed holdings), how alive it
is, and what
Yoke directed it to do (``execution_lane`` + ``mode``, both stored on
``harness_sessions``).

Liveness is derived server-side so no consumer re-encodes TTL numbers:

* ``ended`` — ``ended_at`` or ``terminated_at`` is set. A kill is gone the
  same way an ordinary end is gone; what separates them is the ``ended_cause``
  facet below, not a liveness state of its own.
* ``stale`` — not ended, and the latest activity timestamp
  (``MAX(last_heartbeat, last_tool_call_at)``) is older than the
  executor-aware TTL from
  :func:`yoke_core.domain.session_staleness.activity_is_stale` — the
  same predicate the stale-session reclaim sweep uses.
* ``active`` — not ended and the activity timestamp is fresh.

``ended_cause`` says how an ended session got there — ``killed`` when
``terminated_at`` is set (permanently non-reactivatable and non-wakeable),
``wound_down`` for an ordinary end (which the SessionEnd defense may still
revive). A session that is not ended has no cause, so the field is ``None``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from yoke_contracts.session_control.liveness import (
    ENDED_CAUSES,
    ENDED_CAUSE_KILLED,
    ENDED_CAUSE_WOUND_DOWN,
    LIVENESS_ACTIVE,
    LIVENESS_ENDED,
    LIVENESS_STALE,
    LIVENESS_STATES,
    ended_session_sql,
    live_session_sql,
)
from yoke_core.domain import db_helpers
from yoke_core.domain.actors import (
    ActorLabelAmbiguous,
    ActorLabelMissing,
    ActorNotFound,
)
from yoke_core.domain.actor_display import actor_display_name
from yoke_core.domain.project_identity import resolve_project_id
from yoke_core.domain.session_focus_attribution import focus_attribution
from yoke_core.domain.session_staleness import activity_is_stale
from yoke_core.domain.session_list_fields import SESSION_LIST_FIELDS
from yoke_core.domain.sessions_holdings_read import (
    active_claims_by_session,
    claimed_blitz_worktree_ids_by_session,
    live_item_claim_holders,
)
from yoke_core.domain.sessions_holdings_projection import session_holdings_by_session
from yoke_core.domain.sessions_list_query import build_sessions_query
from yoke_core.domain.sessions_queries_base import display_claim_item_id
from yoke_core.domain.session_presentation_read import session_presentation
from yoke_core.domain.session_native_process_observation import (
    current_native_process_observation,
)


DEFAULT_SESSIONS_LIST_LIMIT = 100
MAX_SESSIONS_LIST_LIMIT = 500
#: Under the unscoped (``project=None``) roster read with ``per_project=True``,
#: each project and the NULL-project partition gets its own newest-N slice,
#: so a busy project cannot crowd a quiet one
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


def _actor_label(
    conn: Any,
    cache: Dict[int, Optional[str]],
    actor_id: Any,
) -> Optional[str]:
    if actor_id is None:
        return None
    key = int(actor_id)
    if key not in cache:
        try:
            cache[key] = actor_display_name(conn, key)
        except (ActorNotFound, ActorLabelMissing, ActorLabelAmbiguous):
            cache[key] = None
    return cache[key]


def list_sessions(
    *,
    project: Optional[str] = None,
    liveness: Optional[str] = None,
    ended_cause: Optional[str] = None,
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

    ``ended_cause`` narrows within the ended population to one of
    :data:`ENDED_CAUSES`, so a kill stays findable without being a
    liveness peer. It prunes in SQL and implies ``ended``.

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
    if ended_cause is not None and ended_cause not in ENDED_CAUSES:
        raise ValueError(
            f"ended_cause must be one of {', '.join(ENDED_CAUSES)}; got {ended_cause!r}"
        )
    if ended_cause is not None and liveness not in (None, LIVENESS_ENDED):
        raise ValueError(
            f"ended_cause={ended_cause!r} describes ended sessions; it cannot "
            f"combine with liveness={liveness!r}. Drop --liveness, or pass "
            "--liveness ended."
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
        if liveness == LIVENESS_ENDED or ended_cause is not None:
            clauses.append(ended_session_sql("s"))
        elif liveness in (LIVENESS_ACTIVE, LIVENESS_STALE):
            clauses.append(live_session_sql("s"))
        if ended_cause == ENDED_CAUSE_KILLED:
            clauses.append("s.terminated_at IS NOT NULL")
        elif ended_cause == ENDED_CAUSE_WOUND_DOWN:
            clauses.append("s.terminated_at IS NULL")
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
        item_holders = live_item_claim_holders(conn)
        holdings_by_session = session_holdings_by_session(conn)
        blitz_lanes_by_session = claimed_blitz_worktree_ids_by_session(conn)
        label_cache: Dict[int, Optional[str]] = {}
        result: List[Dict[str, Any]] = []
        for raw in rows:
            row = dict(raw)
            activity_at, _parsed = _latest_activity(
                row.get("last_heartbeat"),
                row.get("last_tool_call_at"),
            )
            cause: Optional[str] = None
            if row.get("terminated_at"):
                state = LIVENESS_ENDED
                cause = ENDED_CAUSE_KILLED
            elif row.get("ended_at"):
                state = LIVENESS_ENDED
                cause = ENDED_CAUSE_WOUND_DOWN
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
            focus = focus_attribution(
                session_id,
                current_item_display,
                current_item,
                claims=claims,
                roles=roles_by_session.get(session_id, []),
                item_holders=item_holders,
            )
            executor_surface = row.get("executor_surface")
            presentation = session_presentation(conn, row)
            result.append(
                {
                    "session_id": session_id,
                    "liveness": state,
                    "ended_cause": cause,
                    "activity_at": activity_at,
                    "execution_lane": row.get("execution_lane"),
                    **presentation,
                    "mode": row.get("mode"),
                    "quiet_reason": row.get("quiet_reason"),
                    "keepalive_until": row.get("keepalive_until"),
                    "keepalive_reason": row.get("keepalive_reason"),
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
                    "model": row.get("model"),
                    "reasoning_effort": row.get("reasoning_effort"),
                    "context_window_tokens": row.get("context_window_tokens"),
                    "requested_model": row.get("requested_model"),
                    "workspace": row.get("workspace"),
                    "offered_at": row.get("offered_at"),
                    "native_process": current_native_process_observation(row),
                    "ended_at": row.get("ended_at"),
                    "terminated_at": row.get("terminated_at"),
                    "terminated_by_actor_id": row.get("terminated_by_actor_id"),
                    "terminated_by_session_id": row.get("terminated_by_session_id"),
                    "termination_reason": row.get("termination_reason"),
                    "current_item": current_item_display,
                    "current_item_project_id": row.get(
                        "current_item_project_id",
                    ),
                    "current_item_project_sequence": row.get(
                        "current_item_project_sequence",
                    ),
                    "current_item_title": row.get("current_item_title"),
                    "current_item_status": row.get("current_item_status"),
                    "current_item_workflow_id": row.get(
                        "current_item_workflow_id",
                    ),
                    "current_item_workflow_version_id": row.get(
                        "current_item_workflow_version_id",
                    ),
                    **focus,
                    "claims": claims,
                    "holdings": holdings_by_session.get(session_id)
                    or {
                        "current": [],
                        "previous": [],
                        "previous_remainder": 0,
                        "steered": False,
                    },
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
    "ENDED_CAUSES",
    "LIVENESS_ACTIVE",
    "LIVENESS_ENDED",
    "LIVENESS_STALE",
    "LIVENESS_STATES",
    "MAX_SESSIONS_LIST_LIMIT",
    "PER_PROJECT_SESSIONS_LIST_CAP",
    "SESSION_LIST_FIELDS",
    "list_sessions",
]
