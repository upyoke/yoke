"""How soon a relay should come back when it left wake work behind.

A poll leases one job. That is deliberate -- wakes touch shared session state
and native creates are spaced apart on purpose -- but the cadence the server
hands back with that job was not: it always named the ordinary active
interval, sixty seconds by default, even on a poll that had just walked past
other recipients it could not hand out yet. So a machine holding several
undelivered envelopes drained them at one per minute.

That is not a theoretical cost. Eight recipients queued on one machine within
two minutes were woken at 14:18:14, 14:19:20, 14:21:22, 14:26:26, 14:27:16,
14:28:26, 14:29:26 and 14:30:24 -- one per poll, twelve minutes end to end,
while every one of them had been eligible from the moment it was stored.
Nothing was waiting on a clock, a grace window, or a decision; they were
waiting on the relay's next scheduled visit.

The relay already obeys the cadence the server returns, and has since before
this module existed, so saying "come straight back" needs no new protocol,
no second job slot, and no change to how leases are held. It only needs the
server to say it, on the one poll that knows it is true.

The question is asked permissively on purpose. This reads the receipt facts
the eligibility sweep filters on first -- state, cancellation, expiry, wake
horizon, an injection lease, an attempt already open -- and none of the
per-recipient judgement that follows in Python. A recipient the full sweep
would go on to skip can therefore pull the relay back early, which costs one
poll that finds nothing and then settles to the ordinary cadence. The
opposite error costs another minute per envelope, so the cheap direction is
the one to be wrong in. Nothing here has side effects: it decides a cadence,
never a delivery.
"""

from __future__ import annotations

from typing import Any, Sequence

from yoke_core.domain import db_backend


#: The cadence returned instead of the active interval when a poll leased a
#: job and left more wake work behind. One second is the long-poll step the
#: relay already uses to re-check inside a single visit, so a drain runs at
#: the speed the relay was always willing to work at.
RELAY_DRAIN_POLL_SECONDS = 1


def wake_work_pending(
    conn: Any,
    *,
    machine_id: str,
    project_ids: Sequence[int],
    now: str,
) -> bool:
    """True when this machine still has a wake-eligible receipt waiting.

    ``project_ids`` is the polling relay's own declared set, so a machine is
    only ever pulled back for work it is allowed to execute. An empty set can
    have nothing waiting for it and answers ``False`` without a query.
    """
    projects = tuple(sorted({int(value) for value in project_ids}))
    if not projects or not str(machine_id or "").strip():
        return False
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    placeholders = ",".join(marker for _ in projects)
    row = conn.execute(
        "SELECT 1 FROM session_message_recipients r "
        "JOIN session_messages m ON m.message_id=r.message_id "
        f"WHERE r.machine_id={marker} AND r.project_id IN ({placeholders}) "
        "AND r.state='pending' AND m.cancelled_at IS NULL "
        f"AND r.wake_after<={marker} AND m.expires_at>{marker} "
        "AND (r.injection_lease_id IS NULL OR ("
        "r.injection_lease_expires_at IS NOT NULL "
        f"AND r.injection_lease_expires_at<={marker})) "
        "AND NOT EXISTS (SELECT 1 FROM session_message_attempts a "
        "WHERE a.message_id=r.message_id "
        "AND a.target_session_id=r.session_id "
        "AND a.attempt_kind IN ('wake_relay','wake_broker') "
        "AND a.completed_at IS NULL) LIMIT 1",
        (machine_id, *projects, now, now, now),
    ).fetchone()
    return row is not None


__all__ = ["RELAY_DRAIN_POLL_SECONDS", "wake_work_pending"]
