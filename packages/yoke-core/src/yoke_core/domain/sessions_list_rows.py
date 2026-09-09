"""Project fetched session-roster SQL rows into the public list shape."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from yoke_contracts.session_control.liveness import (
    ENDED_CAUSE_KILLED,
    ENDED_CAUSE_WOUND_DOWN,
    LIVENESS_ACTIVE,
    LIVENESS_ENDED,
    LIVENESS_STALE,
)
from yoke_core.domain.actor_render import render_actor_name
from yoke_core.domain.session_focus_attribution import focus_attribution
from yoke_core.domain.session_list_fields import usage_fields
from yoke_core.domain.session_native_process_observation import (
    current_native_process_observation,
)
from yoke_core.domain.sessions_holdings_claim_facts import (
    ITEM_AWAITING_LANDING_KEY,
)
from yoke_core.domain.session_presentation_read import session_presentation
from yoke_core.domain.session_staleness import activity_is_stale
from yoke_core.domain.sessions_queries_base import display_claim_item_id


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
    """One roster cell per actor, resolved once and omitted when absent."""
    if actor_id is None:
        return None
    key = int(actor_id)
    if key not in cache:
        cache[key] = render_actor_name(conn, key)
    return cache[key]


def render_session_roster_rows(
    conn: Any,
    rows: List[Any],
    *,
    liveness: Optional[str],
    claims_by_session: Dict[str, List[Dict[str, Any]]],
    roles_by_session: Dict[str, List[Dict[str, Any]]],
    item_holders: Dict[int, str],
    holdings_by_session: Dict[str, Dict[str, Any]],
    blitz_lanes_by_session: Dict[str, List[int]],
) -> List[Dict[str, Any]]:
    """Classify liveness and attach holdings for already-fetched roster rows."""
    label_cache: Dict[int, Optional[str]] = {}
    result: List[Dict[str, Any]] = []
    empty_holdings = {
        "current": [],
        "previous": [],
        "previous_remainder": 0,
        "steered": False,
    }
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
        elif activity_is_stale(activity_at, executor=row.get("executor")):
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
        presentation = session_presentation(conn, row)
        holdings = holdings_by_session.get(session_id) or empty_holdings
        landing_wait = any(
            entry.get(ITEM_AWAITING_LANDING_KEY) for entry in holdings["current"]
        )
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
                "actor_label": _actor_label(conn, label_cache, row.get("actor_id")),
                "project_id": row.get("project_id"),
                "project": row.get("project"),
                "executor": row.get("executor"),
                "executor_surface": row.get("executor_surface"),
                "model": row.get("model"),
                "reasoning_effort": row.get("reasoning_effort"),
                "context_window_tokens": row.get("context_window_tokens"),
                "requested_model": row.get("requested_model"),
                **usage_fields(row),
                "workspace": row.get("workspace"),
                "offered_at": row.get("offered_at"),
                "native_process": current_native_process_observation(
                    row,
                    landing_wait=landing_wait,
                ),
                "ended_at": row.get("ended_at"),
                "terminated_at": row.get("terminated_at"),
                "terminated_by_actor_id": row.get("terminated_by_actor_id"),
                "terminated_by_session_id": row.get("terminated_by_session_id"),
                "termination_reason": row.get("termination_reason"),
                "current_item": current_item_display,
                "current_item_project_id": row.get("current_item_project_id"),
                "current_item_project_sequence": row.get(
                    "current_item_project_sequence",
                ),
                "current_item_title": row.get("current_item_title"),
                "current_item_status": row.get("current_item_status"),
                "current_item_workflow_id": row.get("current_item_workflow_id"),
                "current_item_workflow_version_id": row.get(
                    "current_item_workflow_version_id",
                ),
                **focus,
                "claims": claims,
                "holdings": holdings,
                "claimed_blitz_worktree_ids": blitz_lanes_by_session.get(
                    session_id,
                    [],
                ),
            }
        )
    return result


__all__ = ["render_session_roster_rows"]
