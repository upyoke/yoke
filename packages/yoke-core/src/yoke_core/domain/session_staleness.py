"""Shared executor-aware session staleness predicates and the liveness projection."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Mapping, Optional

from yoke_contracts.session_control.liveness import (
    LIVENESS_ACTIVE,
    LIVENESS_ENDED,
    LIVENESS_STALE,
    LIVENESS_WAITING,
)
from yoke_contracts.timestamps import as_utc, parse_instant, utc_now

from .sessions_analytics_core import DEFAULT_STALE_THRESHOLD_MINUTES
from .sessions_render_reclaim import _resolve_effective_ttl


def _parse_timestamp(value: object) -> Optional[datetime]:
    return parse_instant(value) if value is not None else None


def activity_is_stale(
    activity_at: object,
    *,
    executor: Optional[str],
    now: Optional[datetime] = None,
    base_ttl_minutes: int = DEFAULT_STALE_THRESHOLD_MINUTES,
    executor_ttl_overrides: Optional[Mapping[str, int]] = None,
) -> bool:
    """Return whether ``activity_at`` is stale for the executor's TTL."""
    parsed = _parse_timestamp(activity_at)
    if parsed is None:
        return True
    now_dt = utc_now() if now is None else as_utc(now)
    ttl = _resolve_effective_ttl(
        executor,
        base_ttl_minutes,
        dict(executor_ttl_overrides) if executor_ttl_overrides is not None else None,
    )
    return parsed < now_dt - timedelta(minutes=ttl)


#: The row column :func:`session_liveness` reads the claim fact from; select
#: ``holds_work_claim_sql(alias) AS holds_work_claim`` to supply it.
HOLDS_WORK_CLAIM_COLUMN = "holds_work_claim"


def activity_liveness(row: Mapping[str, Any], *, now: Optional[datetime] = None) -> str:
    """Route by hook reachability, without treating that as working activity.

    Heartbeat may prove responsive hooks while the model reports tool silence.
    It never supersedes a native process death. Routing TTL is independent of
    the project's tool-idle threshold.
    """
    from .session_state import session_state

    state = session_state(row, now=now)
    if state["presence"] == "ended":
        return LIVENESS_ENDED
    if state["presence"] == "gone":
        return LIVENESS_STALE
    candidates = [
        parse_instant(row[key])
        for key in ("last_heartbeat", "last_tool_call_at", "activity_at")
        if row.get(key) is not None
    ]
    activity_at = max(candidates) if candidates else None
    return (
        LIVENESS_STALE
        if activity_is_stale(activity_at, executor=row.get("executor"), now=now)
        else LIVENESS_ACTIVE
    )


def session_liveness(row: Mapping[str, Any], *, now: Optional[datetime] = None) -> str:
    """Project reclaim eligibility and explicit intent for legacy selectors."""
    from .session_state import session_state

    if (
        not (row.get("terminated_at") or row.get("ended_at"))
        and HOLDS_WORK_CLAIM_COLUMN not in row
    ):
        raise KeyError(
            "session liveness needs the row's holds_work_claim fact: select "
            "holds_work_claim_sql(<alias>) AS holds_work_claim in the session read"
        )
    state = session_state(row, now=now)
    if state["presence"] == "ended":
        return LIVENESS_ENDED
    if row.get(HOLDS_WORK_CLAIM_COLUMN) and state["intent"]["state"] != "none":
        return LIVENESS_WAITING
    return LIVENESS_STALE if state["custody"]["reclaimable"] else LIVENESS_ACTIVE
