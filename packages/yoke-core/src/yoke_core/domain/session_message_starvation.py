"""When a live-looking session's hook route will not feed an envelope.

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

A session that stamped ``parked`` declares the same absence up front, and on
a harness with no idle wake it declares it conclusively: parked is a wait
the session chose, it makes no tool calls while it holds, and a harness
whose manifest reports ``idle_wake: none`` has no primitive that could
resume the turn from outside. Nothing is coming that would run a hook, so
there is nothing to wait out — the grace window would only postpone the wake
that is the sole way in. One clearance sat seven minutes against a parked
codex worker at zero wake attempts until a person resumed it by hand. Such a
recipient therefore escalates on the first pass it is seen. Where the
harness does declare an idle wake, the session can still be resumed by its
own machinery, so a parked recipient there stays with the evidence-bound
test above.

Escalating is a wake, not a page: nothing here asks an operator for
anything. The reason travels on the recipient row and on the wake attempt so
that an operator reading the message can tell an escalated resume from an
ordinary one, and which of the two absences authorized it.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Mapping

from yoke_contracts.harness_wake_capability import wake_capability_for_harness
from yoke_core.domain.session_message_types import parse_timestamp
from yoke_core.domain.session_mode import session_is_parked


#: Recorded on the receipt and wake attempt this escalation authorized.
STARVED_HOOK_ROUTE = "starved_hook_route"
#: The same record, for a declared wait no hook event is going to end.
PARKED_WITHOUT_IDLE_WAKE = "parked_without_idle_wake"


def _undelivered_since_send(row: Mapping[str, Any], *, now: datetime) -> bool:
    """True when nothing has attached this envelope and no hook has run.

    A tool call after the message arrived means a hook ran and declined to
    attach it. That is a delivery defect with its own probe record, not an
    absent route, and resuming the session would not fix it.
    """
    if str(row.get("state") or "") != "pending":
        return False
    if int(row.get("injection_count") or 0) > 0:
        return False
    created = parse_timestamp(row.get("message_created_at"))
    if created is None:
        return False
    last_tool_call = parse_timestamp(row.get("last_tool_call_at"))
    return last_tool_call is None or last_tool_call <= created


def _escalated_wake_available(
    row: Mapping[str, Any],
    *,
    window: timedelta,
    now: datetime,
    ignore_wake_cooldown: bool,
) -> bool:
    """One escalated wake per recipient per window.

    The resume spawns a real process; a second one racing the first is the
    failure this guards.
    """
    if ignore_wake_cooldown:
        return True
    last_wake = parse_timestamp(row.get("last_wake_at"))
    return last_wake is None or last_wake + window <= now


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
    if not _undelivered_since_send(row, now=now):
        return False
    window = timedelta(seconds=grace_seconds)
    created = parse_timestamp(row.get("message_created_at"))
    if created is None or created + window > now:
        return False
    return _escalated_wake_available(
        row,
        window=window,
        now=now,
        ignore_wake_cooldown=ignore_wake_cooldown,
    )


def parked_without_idle_wake(
    row: Mapping[str, Any],
    *,
    grace_seconds: int,
    now: datetime,
    ignore_wake_cooldown: bool = False,
) -> bool:
    """True when the recipient parked on a harness that cannot wake itself.

    ``row`` and ``ignore_wake_cooldown`` are as above. No waiting window is
    consulted before the first wake: the two facts that decide this are the
    posture the session declared about itself and the wake primitive its
    harness family does or does not have, and neither becomes truer by
    waiting. An unprobed harness declares ``unverified`` rather than
    ``none``, so it is not escalated here — the contract refuses to guess,
    and so does this. The window still spaces repeat wakes apart.
    """
    if not _undelivered_since_send(row, now=now):
        return False
    if not session_is_parked(row.get("mode")):
        return False
    if wake_capability_for_harness(row.get("executor")).idle_wake != "none":
        return False
    return _escalated_wake_available(
        row,
        window=timedelta(seconds=grace_seconds),
        now=now,
        ignore_wake_cooldown=ignore_wake_cooldown,
    )


__all__ = [
    "PARKED_WITHOUT_IDLE_WAKE",
    "STARVED_HOOK_ROUTE",
    "parked_without_idle_wake",
    "starved_hook_route",
]
