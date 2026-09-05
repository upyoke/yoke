"""Idle-timeout native wake eligibility for a fleet message recipient.

Split out of ``session_message_delivery`` (which re-exports ``wake_eligible``
for its existing callers) purely to keep that module's delivery-and-report
rendering under the authored-file line cap; this is otherwise the same
function, unchanged.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


_DELIVERABLE_STATES = frozenset({"pending"})


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


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
    if recipient_state not in _DELIVERABLE_STATES:
        return False
    if last_activity_at is None:
        return True
    return _as_utc(now) - _as_utc(last_activity_at) >= idle_threshold


__all__ = ["wake_eligible"]
