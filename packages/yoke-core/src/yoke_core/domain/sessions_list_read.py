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
from yoke_core.domain.session_list_fields import SESSION_LIST_FIELDS
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


def _claim_target_display(conn: Any, claim: Dict[str, Any]) -> str:
    kind = str(claim.get("target_kind") or "")
    if kind == "item":
        return str(display_claim_item_id(str(claim.get("item_id")), conn) or "")
    if kind == "epic_task":
        return f"epic {claim.get('epic_id')} task {claim.get('task_num')}"
    return str(claim.get("process_key") or "")


def _active_claims_by_session(
    conn: Any,
) -> Tuple[
    Dict[str, List[Dict[str, Any]]],
    Dict[str, List[Dict[str, Any]]],
]:
    rows = conn.execute(
        "SELECT wc.session_id, wc.target_kind, wc.item_id, wc.epic_id, "
        "wc.task_num, wc.process_key, wc.conflict_group, wc.claimed_at, "
        "wc.reason, COALESCE(task_lane.lane_role, item_lane.lane_role) "
        "AS lane_role "
        "FROM work_claims wc "
        "LEFT JOIN epic_tasks et ON wc.target_kind = 'epic_task' "
        "AND et.epic_id = wc.epic_id AND et.task_num = wc.task_num "
        "LEFT JOIN item_worktrees task_lane "
        "ON task_lane.id = et.item_worktree_id "
        "AND task_lane.state = 'active' "
        "LEFT JOIN item_worktrees item_lane ON item_lane.id = ("
        "SELECT iw.id FROM item_worktrees iw "
        "WHERE wc.target_kind = 'item' AND iw.item_id = wc.item_id "
        "AND iw.state = 'active' "
        "ORDER BY CASE iw.lane_role WHEN 'integration' THEN 0 "
        "WHEN 'implementation' THEN 1 ELSE 2 END, iw.id LIMIT 1"
        ") "
        "WHERE wc.released_at IS NULL ORDER BY wc.claimed_at ASC",
    ).fetchall()
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    roles: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        claim = dict(row)
        session_id = str(claim["session_id"])
        grouped.setdefault(session_id, []).append(
            {
                "target_kind": str(claim.get("target_kind") or ""),
                "target": _claim_target_display(conn, claim),
                "claimed_at": claim.get("claimed_at"),
                "reason": claim.get("reason"),
            }
        )
        claimed_item = (
            claim.get("item_id")
            if claim.get("target_kind") == "item"
            else claim.get("epic_id")
        )
        roles.setdefault(session_id, []).append(
            {
                "target_kind": str(claim.get("target_kind") or ""),
                "item_id": int(claimed_item) if claimed_item is not None else None,
                "lane_role": claim.get("lane_role"),
                "claimed_at": claim.get("claimed_at"),
            }
        )
    return grouped, roles


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
    """
    if liveness is not None and liveness not in LIVENESS_STATES:
        raise ValueError(
            f"liveness must be one of {', '.join(LIVENESS_STATES)}; got {liveness!r}"
        )
    bounded_limit = max(1, min(int(limit), MAX_SESSIONS_LIST_LIMIT))
    windowed = per_project and not project

    conn = db_helpers.connect()
    try:
        clauses: List[str] = []
        where_params: List[Any] = []
        if project:
            clauses.append("s.project_id = %s")
            where_params.append(resolve_project_id(conn, project))
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

        claims_by_session, roles_by_session = _active_claims_by_session(conn)
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
            executor_display_name = row.get("executor_display_name")
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
                    "executor_display_name": executor_display_name,
                    "executor_mark": presentation["executor_mark"],
                    "executor_class_name": presentation["executor_class_name"],
                    "model": row.get("model"),
                    "workspace": row.get("workspace"),
                    "offered_at": row.get("offered_at"),
                    "ended_at": row.get("ended_at"),
                    "current_item": current_item_display,
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
