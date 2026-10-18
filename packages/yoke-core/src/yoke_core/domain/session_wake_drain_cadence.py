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

from datetime import datetime

from yoke_contracts.timestamps import parse_instant
from yoke_core.domain.db_helpers import instant_parameter

from typing import Any, Sequence

from yoke_core.domain import db_backend


#: The cadence returned instead of the active interval when a poll leased a
#: job and left more wake work behind, or while the relay holds a live batch.
#: A live batch admits newly assigned launches, so the relay comes straight
#: back and long-polls for them rather than leaving them a minute behind.
#: One second is the long-poll step the relay already uses to re-check inside
#: a single visit, so a drain runs at the speed the relay was always willing
#: to work at.
RELAY_DRAIN_POLL_SECONDS = 1


def wake_work_pending(
    conn: Any,
    *,
    machine_id: str,
    project_ids: Sequence[int],
    now: datetime | str,
    relay_actor_id: int | None = None,
) -> bool:
    """True when this machine still has a wake-eligible receipt waiting.

    ``project_ids`` is the polling relay's own declared set, so a machine is
    only pulled back for advertised projects or its own actor's org sessions
    on this machine. Without projects or an actor there is no eligible scope.
    """
    projects = tuple(sorted({int(value) for value in project_ids}))
    if (not projects and relay_actor_id is None) or not str(machine_id or "").strip():
        return False
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    placeholders = ",".join(marker for _ in projects)
    scopes = [f"r.project_id IN ({placeholders})"] if projects else []
    scope_params: list[Any] = list(projects)
    if relay_actor_id is not None:
        scopes.append(f"(r.org_id IS NOT NULL AND hs.actor_id={marker})")
        scope_params.append(relay_actor_id)
    row = conn.execute(
        "SELECT 1 FROM session_message_recipients r "
        "JOIN session_messages m ON m.message_id=r.message_id "
        "JOIN harness_sessions hs ON hs.session_id=r.session_id "
        f"WHERE r.machine_id={marker} AND ({' OR '.join(scopes)}) "
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
        (
            machine_id,
            *scope_params,
            instant_parameter(conn, parse_instant(now)),
            instant_parameter(conn, parse_instant(now)),
            instant_parameter(conn, parse_instant(now)),
        ),
    ).fetchone()
    return row is not None


__all__ = ["RELAY_DRAIN_POLL_SECONDS", "wake_work_pending"]
