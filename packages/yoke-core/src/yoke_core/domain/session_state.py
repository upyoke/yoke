"""One projection of session presence, activity, intent, custody and next actor.

Callers supply durable session, holdings and open-call facts, plus the project's
session_idle_minutes. No heartbeat or telemetry event proves process presence
or tool progress. Reclaim policy remains with classify_activity.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Mapping

from yoke_contracts.project_contract.project_keys import DEFAULT_SESSION_IDLE_MINUTES
from yoke_contracts.session_control.liveness import IN_FLIGHT_CEILING_SECONDS
from yoke_contracts.session_queue_posture import (
    session_declared_wait,
)
from yoke_contracts.timestamps import as_utc, parse_instant, temporal_wire, utc_now
from yoke_core.domain.next_actor import session_next_actor
from yoke_core.domain.session_tool_call_liveness import open_call_predates_park
from yoke_core.domain.session_reclaim_progress import open_tool_call_is_live


def session_presence(row: Mapping[str, Any]) -> str:
    """End stamps win; only a later tool call supersedes a process death."""
    if row.get("ended_at") or row.get("terminated_at"):
        return "ended"
    gone = (
        parse_instant(row["native_process_gone_at"])
        if row.get("native_process_gone_at")
        else None
    )
    tool = (
        parse_instant(row["last_tool_call_at"])
        if row.get("last_tool_call_at")
        else None
    )
    return "gone" if gone is not None and (tool is None or tool <= gone) else "present"


def session_in_flight(
    row: Mapping[str, Any], *, now: datetime | None = None
) -> bool:
    """A current running call is bounded by the shared watcher ceiling."""
    started = row.get("open_tool_call_at")
    if (
        started is None
        or session_presence(row) != "present"
    ):
        return False
    now = utc_now() if now is None else as_utc(now)
    stamp = parse_instant(started)
    return timedelta(0) <= now - stamp < timedelta(
        seconds=IN_FLIGHT_CEILING_SECONDS
    ) and (
        row.get("turn_posture") == "running"
        and open_tool_call_is_live(stamp, row.get("last_tool_call_at"))
        and not open_call_predates_park(row, started_at=stamp)
    )


def session_state(
    row: Mapping[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Project the five independent facts without inventing missing custody.

    Raw activity-only readers can omit holds_work_claim; custody then stays
    unknown. Display readers must supply it before asking for reclaimability.
    ``holds`` is the caller's complete active holdings list, when available.
    """
    from yoke_core.domain.session_automatic_reclaim import automatic_reclaim

    current = utc_now() if now is None else as_utc(now)
    presence = session_presence(row)
    declared = session_declared_wait(row)
    intent = (
        "awaiting" if declared else "parked" if row.get("mode") == "parked" else "none"
    )
    next_action = session_next_actor(row, presence=presence)
    if next_action["actor"] in {"operator", "another_item", "ci_or_deploy"}:
        intent = "awaiting"
    reason = next_action["reason"] if intent == "awaiting" else row.get("quiet_reason")
    tool = (
        parse_instant(row["last_tool_call_at"])
        if row.get("last_tool_call_at")
        else None
    )
    idle_minutes = row.get("session_idle_minutes", DEFAULT_SESSION_IDLE_MINUTES)
    fresh = tool is not None and tool >= current - timedelta(minutes=idle_minutes)
    in_flight = session_in_flight(row, now=current)
    activity = "silent"
    if presence == "present" and (fresh or in_flight):
        activity = (
            "working"
            if intent == "none" and row.get("turn_posture") == "running"
            else "between_turns"
        )
    reclaim = automatic_reclaim(row, now=current) if "holds_work_claim" in row else None
    holds = row.get("holds", row.get("claims", []))
    return temporal_wire(
        {
            "presence": presence,
            "activity": activity,
            "intent": {
                "state": intent,
                "reason": reason if intent != "none" else None,
                "awaiting_who": next_action["actor"] if intent == "awaiting" else None,
            },
            "custody": {
                "holds": list(holds),
                "holds_work_claim": row.get("holds_work_claim"),
                "reclaimable": reclaim.is_reclaimable if reclaim else None,
                "reason": reclaim.reason if reclaim else "custody_facts_unavailable",
            },
            "next_actor": next_action,
            "in_flight": in_flight,
        }
    )
