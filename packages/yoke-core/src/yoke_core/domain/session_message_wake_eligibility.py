"""Idle-timeout wake eligibility with strict native activity clocks."""

from __future__ import annotations

from datetime import datetime, timedelta

from yoke_contracts.timestamps import as_utc


_DELIVERABLE_STATES = frozenset({"pending"})


def wake_eligible(
    *,
    recipient_state: str,
    last_activity_at: datetime | None,
    now: datetime,
    idle_threshold: timedelta,
) -> bool:
    """Return whether a recipient may enter idle-timeout native wake routing.

    The wake sweep uses one idleness clock: time since the latest hook, tool
    call, injection, or heartbeat. A session still inside that window is
    left to hook injection; once idleness reaches the threshold, wake may
    run. ``wake_after`` is stamped at send so eligibility is not delayed.
    """
    current = as_utc(now)
    activity = as_utc(last_activity_at) if last_activity_at is not None else None
    if recipient_state not in _DELIVERABLE_STATES:
        return False
    if activity is None:
        return True
    return current - activity >= idle_threshold


__all__ = ["wake_eligible"]
