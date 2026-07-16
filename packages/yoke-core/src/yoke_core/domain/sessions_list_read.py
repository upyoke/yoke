"""Read-only session roster with liveness and held-claims derivation.

The read behind ``sessions.list``: one row per harness session carrying
the attribution facts (actor id/kind plus the canonical display label),
what the session holds (its active work-claims, typed targets rendered
to display strings), how alive it is, and what Yoke directed it to do
(``execution_lane`` + ``mode``, both stored on ``harness_sessions``).

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
from yoke_core.domain.sessions_queries_base import display_claim_item_id


LIVENESS_ACTIVE = "active"
LIVENESS_STALE = "stale"
LIVENESS_ENDED = "ended"
LIVENESS_STATES = (LIVENESS_ACTIVE, LIVENESS_STALE, LIVENESS_ENDED)

DEFAULT_SESSIONS_LIST_LIMIT = 100
MAX_SESSIONS_LIST_LIMIT = 500

#: Row keys every ``sessions.list`` row carries, in presentation order.
#: ``claims`` is a list of ``{target_kind, target, claimed_at, reason}``
#: dicts; every other field is a scalar.
SESSION_LIST_FIELDS = (
    "session_id",
    "liveness",
    "activity_at",
    "execution_lane",
    "mode",
    "actor_id",
    "actor_kind",
    "actor_label",
    "project_id",
    "project",
    "executor",
    "model",
    "workspace",
    "offered_at",
    "ended_at",
    "current_item",
    "claims",
)


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


def _claim_target_display(claim: Dict[str, Any]) -> str:
    kind = str(claim.get("target_kind") or "")
    if kind == "item":
        return str(display_claim_item_id(str(claim.get("item_id"))) or "")
    if kind == "epic_task":
        return f"epic {claim.get('epic_id')} task {claim.get('task_num')}"
    return str(claim.get("process_key") or "")


def _active_claims_by_session(conn: Any) -> Dict[str, List[Dict[str, Any]]]:
    rows = conn.execute(
        "SELECT session_id, target_kind, item_id, epic_id, task_num, "
        "process_key, conflict_group, claimed_at, reason "
        "FROM work_claims WHERE released_at IS NULL "
        "ORDER BY claimed_at ASC",
    ).fetchall()
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        claim = dict(row)
        grouped.setdefault(str(claim["session_id"]), []).append({
            "target_kind": str(claim.get("target_kind") or ""),
            "target": _claim_target_display(claim),
            "claimed_at": claim.get("claimed_at"),
            "reason": claim.get("reason"),
        })
    return grouped


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
) -> List[Dict[str, Any]]:
    """List harness sessions, newest activity first.

    ``project`` filters on the session's own ``project_id`` binding
    (slug or id, resolved server-side). ``liveness`` filters to one of
    :data:`LIVENESS_STATES`; the ended/not-ended half of that split
    prunes in SQL, while the active/stale split classifies within the
    ``limit`` window (the TTL is executor-aware, so it cannot live in
    the WHERE clause).
    """
    if liveness is not None and liveness not in LIVENESS_STATES:
        raise ValueError(
            f"liveness must be one of {', '.join(LIVENESS_STATES)}; "
            f"got {liveness!r}"
        )
    bounded_limit = max(1, min(int(limit), MAX_SESSIONS_LIST_LIMIT))

    conn = db_helpers.connect()
    try:
        clauses: List[str] = []
        params: List[Any] = []
        if project:
            clauses.append("s.project_id = %s")
            params.append(resolve_project_id(conn, project))
        if liveness == LIVENESS_ENDED:
            clauses.append("s.ended_at IS NOT NULL")
        elif liveness in (LIVENESS_ACTIVE, LIVENESS_STALE):
            clauses.append("s.ended_at IS NULL")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(bounded_limit)

        # Timestamps are uniform ISO-8601 text, so lexicographic GREATEST
        # matches chronological order for the coarse fetch window; the
        # precise per-row classification below re-parses real datetimes.
        rows = conn.execute(
            "SELECT s.session_id, s.executor, s.model, s.execution_lane, "
            "s.mode, s.workspace, s.project_id, pr.slug AS project, "
            "s.offered_at, s.last_heartbeat, s.last_tool_call_at, "
            "s.ended_at, s.current_item_id, s.actor_id, "
            "a.kind AS actor_kind "
            "FROM harness_sessions s "
            "LEFT JOIN projects pr ON pr.id = s.project_id "
            "LEFT JOIN actors a ON a.id = s.actor_id "
            f"{where} "
            "ORDER BY GREATEST(COALESCE(s.last_tool_call_at, ''), "
            "s.last_heartbeat) DESC "
            "LIMIT %s",
            tuple(params),
        ).fetchall()

        claims_by_session = _active_claims_by_session(conn)
        label_cache: Dict[int, str] = {}
        result: List[Dict[str, Any]] = []
        for raw in rows:
            row = dict(raw)
            activity_at, _parsed = _latest_activity(
                row.get("last_heartbeat"), row.get("last_tool_call_at"),
            )
            if row.get("ended_at"):
                state = LIVENESS_ENDED
            elif activity_is_stale(
                activity_at, executor=row.get("executor"),
            ):
                state = LIVENESS_STALE
            else:
                state = LIVENESS_ACTIVE
            if liveness is not None and state != liveness:
                continue
            session_id = str(row["session_id"])
            current_item = row.get("current_item_id")
            result.append({
                "session_id": session_id,
                "liveness": state,
                "activity_at": activity_at,
                "execution_lane": row.get("execution_lane"),
                "mode": row.get("mode"),
                "actor_id": row.get("actor_id"),
                "actor_kind": row.get("actor_kind"),
                "actor_label": _actor_label(
                    conn, label_cache, row.get("actor_id"),
                ),
                "project_id": row.get("project_id"),
                "project": row.get("project"),
                "executor": row.get("executor"),
                "model": row.get("model"),
                "workspace": row.get("workspace"),
                "offered_at": row.get("offered_at"),
                "ended_at": row.get("ended_at"),
                "current_item": (
                    display_claim_item_id(str(current_item))
                    if current_item else None
                ),
                "claims": claims_by_session.get(session_id, []),
            })
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
    "SESSION_LIST_FIELDS",
    "list_sessions",
]
