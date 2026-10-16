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
from yoke_contracts.session_queue_posture import session_pause_declared
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
    """``ended``, ``stale`` or ``active`` from the end stamps and activity alone.

    This is what wake and message routing key on: whether the session's own
    hooks are still running is a question of activity, not of what the session
    declared. A roster row that already carries its ``activity_at`` (the later
    of the two stamps) answers the same way as the raw session row.
    """
    if row.get("terminated_at") or row.get("ended_at"):
        return LIVENESS_ENDED
    candidates = [
        parse_instant(row[key])
        for key in ("last_heartbeat", "last_tool_call_at", "activity_at")
        if row.get(key) is not None
    ]
    activity_at = max(candidates) if candidates else None
    if activity_is_stale(activity_at, executor=row.get("executor"), now=now):
        return LIVENESS_STALE
    return LIVENESS_ACTIVE


def session_liveness(row: Mapping[str, Any], *, now: Optional[datetime] = None) -> str:
    """Report stale exactly when automatic reclaim is eligible.

    Intentional pauses on protected work report waiting (shown as parked).
    Activity-only routing remains independent of this display classification.
    """
    if row.get("terminated_at") or row.get("ended_at"):
        return LIVENESS_ENDED
    if HOLDS_WORK_CLAIM_COLUMN not in row:
        raise KeyError(
            "session liveness needs the row's holds_work_claim fact: select "
            "holds_work_claim_sql(<alias>) AS holds_work_claim in the session read"
        )
    if row[HOLDS_WORK_CLAIM_COLUMN] and session_pause_declared(row):
        return LIVENESS_WAITING
    from .session_automatic_reclaim import automatic_reclaim

    return (
        LIVENESS_STALE
        if automatic_reclaim(row, now=now).is_reclaimable
        else LIVENESS_ACTIVE
    )
