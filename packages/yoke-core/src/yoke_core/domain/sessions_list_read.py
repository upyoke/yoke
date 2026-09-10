"""Read-only session roster with liveness and held-claims derivation.

The read behind ``sessions.list``: one row per harness session carrying
the attribution facts (actor id/kind plus the canonical display label),
what the session holds (its current and previous typed holdings), how alive it
is, and what Yoke directed it to do (``execution_lane`` + ``mode``).

Liveness is derived server-side so no consumer re-encodes TTL numbers:

* ``ended`` — ``ended_at`` or ``terminated_at`` is set. A kill is gone the
  same way an ordinary end is gone; what separates them is the ``ended_cause``
  facet below, not a liveness state of its own.
* ``stale`` — not ended, and the latest activity timestamp is older than the
  executor-aware TTL from
  :func:`yoke_core.domain.session_staleness.activity_is_stale`.
* ``active`` — not ended and the activity timestamp is fresh.

Probe sessions never appear at all: a harness startup process that
registered, did nothing and ended is excluded by the shared predicate in
:mod:`yoke_core.domain.session_probe`, whatever the caller's filters say.

``ended_cause`` says how an ended session got there — ``killed`` when
``terminated_at`` is set, ``wound_down`` for an ordinary end.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

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
from yoke_core.domain.project_identity import resolve_project_id
from yoke_core.domain.session_list_fields import SESSION_LIST_FIELDS
from yoke_core.domain.session_probe import not_probe_session_sql
from yoke_core.domain.sessions_holdings_read import (
    active_claims_by_session,
    claimed_blitz_worktree_ids_by_session,
    live_item_claim_holders,
)
from yoke_core.domain.sessions_holdings_projection import session_holdings_by_session
from yoke_core.domain.sessions_list_query import build_sessions_query
from yoke_core.domain.sessions_list_rows import render_session_roster_rows
from yoke_core.domain.work_claim_targets import scope_int_sql


DEFAULT_SESSIONS_LIST_LIMIT = 100
MAX_SESSIONS_LIST_LIMIT = 500
#: Under the unscoped (``project=None``) roster read with ``per_project=True``,
#: each project and the NULL-project partition gets its own newest-N slice,
#: so a busy project cannot crowd a quiet one
#: out of the fetch window. Opt-in so the flat unscoped read (search, the full
#: roster view) keeps its universe-wide newest-N behavior.
PER_PROJECT_SESSIONS_LIST_CAP = 20


def list_sessions(
    *,
    project: Optional[str] = None,
    liveness: Optional[str] = None,
    ended_cause: Optional[str] = None,
    limit: int = DEFAULT_SESSIONS_LIST_LIMIT,
    per_project: bool = False,
    session_id: Optional[str] = None,
    open: bool = False,
) -> List[Dict[str, Any]]:
    """List harness sessions, newest activity first.

    ``project`` filters on the session's own ``project_id`` binding
    (slug or id, resolved server-side), OR-ed with an actual live steering
    claim scoped to that project — a session steers a project it did not
    start in, and that live claim is a project-membership fact just like
    the home-project binding is. A released claim or an ended session
    never adds visibility this way. ``liveness`` filters to one of
    :data:`LIVENESS_STATES`; the ended/not-ended half of that split
    prunes in SQL, while the active/stale split classifies within the
    ``limit`` window (the TTL is executor-aware, so it cannot live in
    the WHERE clause).

    ``open`` keeps the complete live set (active and stale) in SQL before
    any per-project window, so ended rows cannot crowd holders out of Ready.

    ``ended_cause`` narrows within the ended population to one of
    :data:`ENDED_CAUSES`. It prunes in SQL and implies ``ended``.

    ``per_project`` only takes effect on the unscoped roster
    (``project=None``): the fetch window becomes each project's own
    newest-:data:`PER_PROJECT_SESSIONS_LIST_CAP` slice.

    ``session_id`` selects exactly one session through the same row renderer
    and enrichment pipeline.
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
    if open and (liveness == LIVENESS_ENDED or ended_cause is not None):
        raise ValueError(
            "open=True selects live sessions; it cannot combine with "
            f"liveness={liveness!r} or ended_cause={ended_cause!r}."
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
            project_id = resolve_project_id(conn, project)
            steering_project = scope_int_sql(conn, "wc.scope", "project_id")
            clauses.append(
                "(s.project_id = %s OR EXISTS ("
                "SELECT 1 FROM work_claims wc "
                "WHERE wc.session_id = s.session_id "
                "AND wc.target_kind = 'steering' "
                "AND wc.released_at IS NULL "
                f"AND {live_session_sql('s')} "
                f"AND {steering_project} = %s))"
            )
            where_params.append(project_id)
            where_params.append(project_id)
        if normalized_session_id:
            clauses.append("s.session_id = %s")
            where_params.append(normalized_session_id)
        clauses.append(not_probe_session_sql("s"))
        if liveness == LIVENESS_ENDED or ended_cause is not None:
            clauses.append(ended_session_sql("s"))
        elif open or liveness in (LIVENESS_ACTIVE, LIVENESS_STALE):
            clauses.append(live_session_sql("s"))
        if ended_cause == ENDED_CAUSE_KILLED:
            clauses.append("s.terminated_at IS NOT NULL")
        elif ended_cause == ENDED_CAUSE_WOUND_DOWN:
            clauses.append("s.terminated_at IS NULL")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        query = build_sessions_query(where, windowed=windowed)
        if windowed:
            params = [*where_params, PER_PROJECT_SESSIONS_LIST_CAP, bounded_limit]
        else:
            params = [*where_params, bounded_limit]
        rows = conn.execute(query, tuple(params)).fetchall()
        session_ids = [str(dict(raw)["session_id"]) for raw in rows]
        claims_by_session, roles_by_session = active_claims_by_session(
            conn, session_ids=session_ids,
        )
        return render_session_roster_rows(
            conn,
            rows,
            liveness=liveness,
            claims_by_session=claims_by_session,
            roles_by_session=roles_by_session,
            item_holders=live_item_claim_holders(conn),
            holdings_by_session=session_holdings_by_session(
                conn, session_ids=session_ids,
            ),
            blitz_lanes_by_session=claimed_blitz_worktree_ids_by_session(
                conn, session_ids=session_ids,
            ),
        )
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
