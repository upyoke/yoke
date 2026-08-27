"""When a live-looking session's hook route has stopped feeding an envelope.

Hook delivery is the cheap route and the right one for a session that is
working: every tool call runs a hook, and the hook attaches whatever is
pending. The route's whole premise is that the session's turn keeps ticking.

A session can hold a fresh heartbeat while its turn never calls another
tool — parked mid-turn, blocked on something outside the harness, waiting on
input nobody is going to type. Liveness reads ``active`` because the
heartbeat is what liveness measures, so the wake sweep keeps deferring to a
hook route that has already stopped running, and the envelope waits on a
delivery that will never happen. One sat 53 minutes at zero injections; a
second, four hours later, sat pending against a session reading ``active``
the whole time. Neither is a slow delivery — both are a route that ended.

The envelope itself proves it. Zero injections after the message has been
sitting longer than the acknowledgement grace window says nothing on its
own, because a session that never had work to do also injects nothing. What
closes it is the recipient's own clock: no tool call since the message was
created means no hook has run for this session in that whole window, and a
hook is the only thing that could have attached the envelope. At that point
the route is not slow, it is absent — so the wake escalates to the
stopped-session native-resume path even though liveness still reads active.

Escalating is a wake, not a page: nothing here asks an operator for
anything. The reason travels on the wake attempt so that an operator
reading the message can tell an escalated resume from an ordinary one.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Mapping

from yoke_core.domain.session_message_types import parse_timestamp


#: Recorded on the wake attempt that this escalation authorized.
STARVED_HOOK_ROUTE = "starved_hook_route"


def starved_hook_route(
    row: Mapping[str, Any],
    *,
    grace_seconds: int,
    now: datetime,
    ignore_wake_cooldown: bool = False,
) -> bool:
    """True when this receipt's hook route has demonstrably stopped running.

    ``row`` is one eligibility row: the recipient joined to its message and
    its session. The same window bounds both halves of the question — how
    long the envelope has waited, and how long one escalated wake stays the
    only one in flight for that recipient.

    ``ignore_wake_cooldown`` is for the caller re-deriving a candidate whose
    wake it has already stamped — the broker adoption reads the receipt back
    after reserving it, and its own reservation would otherwise read as a
    competing wake and disqualify the escalation it is carrying out.
    """
    if str(row.get("state") or "") != "pending":
        return False
    if int(row.get("injection_count") or 0) > 0:
        return False
    window = timedelta(seconds=grace_seconds)
    created = parse_timestamp(row.get("message_created_at"))
    if created is None or created + window > now:
        return False
    # A tool call after the message arrived means a hook ran and declined to
    # attach it. That is a delivery defect with its own probe record, not an
    # absent route, and resuming the session would not fix it.
    last_tool_call = parse_timestamp(row.get("last_tool_call_at"))
    if last_tool_call is not None and last_tool_call > created:
        return False
    # One escalated wake per recipient per window. The resume spawns a real
    # process; a second one racing the first is the failure this guards.
    if ignore_wake_cooldown:
        return True
    last_wake = parse_timestamp(row.get("last_wake_at"))
    return last_wake is None or last_wake + window <= now


__all__ = ["STARVED_HOOK_ROUTE", "starved_hook_route"]
