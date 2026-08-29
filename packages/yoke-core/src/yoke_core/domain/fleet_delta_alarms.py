"""Negative-space alarms: the failures that arrive as silence.

A steering pass consumes events, and events only report things that
happened. These detectors report things that did not: a claim holder
that went quiet, an in-flight item nobody picked back up, an envelope
that was never delivered. Each is a *level* condition rather than an
edge, so each fires once when it starts and clears once when it stops —
re-firing every pass is how a report becomes noise the reader skims.

The thresholds belong to the steering loop; they are restated here as
the constants the detectors read.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable

from yoke_core.domain.fleet_delta_snapshot import (
    EnvelopeRow,
    FleetSnapshot,
    SessionRow,
)

#: A live work-claim holder silent this long is probed and revived. Its
#: liveness label stays ``active`` far past this point, so the age of the
#: last tool call is the only usable signal.
IDLE_HOLDER_MINUTES = 20
#: A non-terminal item may be momentarily unowned at every lifecycle
#: segment boundary. Only continuous absence this long is a finding.
UNOWNED_ITEM_MINUTES = 15
#: An envelope never injected after this long, to a recipient that has
#: made no tool call since it was sent, is starved rather than in flight.
STARVED_ENVELOPE_MINUTES = 10

#: Envelope states that mean the recipient has not dealt with it yet.
UNREAD_STATES = frozenset({"pending", "injected"})

#: Statuses that are in the backlog rather than in flight; an unclaimed
#: idea is the normal resting state, not an abandoned lane.
BACKLOG_STATUSES = frozenset({"idea"})

LINE_PREFIX = "fleet"


def identifier(value: str) -> str:
    """Return an identifier whole, or ``unknown`` when it is absent.

    Never a leading fragment. Session ids are not uniformly distributed:
    some are readable strings whose first characters are a constant, and
    the UUID-shaped ones are time-ordered, so sessions started in the
    same window share leading hex by construction. A prefix therefore
    names a set rather than a session, and a reader who copies one out
    of a line can address the wrong worker.
    """
    return value if value else "unknown"


def address_recipe(session_id: str, current: FleetSnapshot) -> str:
    """The send form that reaches this session without a copied id.

    A live item claim has exactly one holder, so the item reference is
    an unambiguous address where a session id is only an identity. A
    session holding no item has no such address and is named directly.
    """
    row = current.sessions.get(session_id)
    held = row.claimed_items if row else ()
    if held:
        return f"yoke say --item {held[0]} --stdin"
    return f"yoke say --session {identifier(session_id)} --stdin"


def minutes_since(since: datetime | None, now: datetime) -> int | None:
    """Whole minutes between *since* and *now*, or ``None`` if unknown."""
    if since is None:
        return None
    return int((now - since).total_seconds() // 60)


@dataclass
class DeltaState:
    """Cross-pass memory: alarm dedupe plus unowned-since continuity."""

    active_alarms: set[str] = field(default_factory=set)
    unowned_since: dict[str, datetime] = field(default_factory=dict)


def _raise_once(state: DeltaState, key: str, line: str) -> list[str]:
    """Emit *line* only when *key* was not already alarming."""
    if key in state.active_alarms:
        return []
    state.active_alarms.add(key)
    return [line]


def _clear(state: DeltaState, live_keys: set[str], kind: str) -> list[str]:
    """Emit one clear line per alarm of *kind* that is no longer live."""
    resolved = sorted(
        key
        for key in state.active_alarms
        if key.startswith(f"{kind}:") and key not in live_keys
    )
    for key in resolved:
        state.active_alarms.discard(key)
    return [f"{LINE_PREFIX} CLEAR {kind} {key.split(':', 1)[1]}" for key in resolved]


def _holding_sessions(current: FleetSnapshot) -> Iterable[SessionRow]:
    """Live, unparked sessions holding at least one item claim."""
    return [
        row
        for _, row in sorted(current.sessions.items())
        if row.lifecycle == "live" and not row.parked and row.claimed_items
    ]


def idle_holder_alarms(current: FleetSnapshot, state: DeltaState) -> list[str]:
    """Live claim holders silent past the idle threshold.

    A session that stamped ``parked`` declared its wait and is excluded;
    every other silent holder is burning down its own stale clock while
    the item it owns still reads as staffed.
    """
    lines: list[str] = []
    live: set[str] = set()
    for row in _holding_sessions(current):
        idle = minutes_since(row.activity_at, current.taken_at)
        if idle is None or idle < IDLE_HOLDER_MINUTES:
            continue
        key = f"idle-holder:session={identifier(row.session_id)}"
        live.add(key)
        lines.extend(
            _raise_once(
                state,
                key,
                f"{LINE_PREFIX} ALARM idle-holder "
                f"session={identifier(row.session_id)} "
                f"items={','.join(row.claimed_items)} idle={idle}m "
                f"surface={row.executor_surface} "
                f"reach={address_recipe(row.session_id, current)!r}",
            )
        )
    return lines + _clear(state, live, "idle-holder")


def unowned_item_alarms(current: FleetSnapshot, state: DeltaState) -> list[str]:
    """In-flight items unowned continuously past the unowned threshold.

    Continuity is measured from the first pass that observed the item
    unowned, never from a single snapshot: every lifecycle segment
    boundary releases the claim and reacquires moments later, and a
    sweep that reads that window as abandonment staffs a second worker
    onto live work.
    """
    lines: list[str] = []
    live: set[str] = set()
    for ref in sorted(current.items):
        row = current.items[ref]
        if not row.unclaimed or row.status in BACKLOG_STATUSES:
            state.unowned_since.pop(ref, None)
            continue
        since = state.unowned_since.setdefault(ref, current.taken_at)
        unowned = minutes_since(since, current.taken_at) or 0
        if unowned < UNOWNED_ITEM_MINUTES:
            continue
        key = f"unowned-item:{ref}"
        live.add(key)
        lines.extend(
            _raise_once(
                state,
                key,
                f"{LINE_PREFIX} ALARM unowned-item {ref} "
                f"status={row.status} unowned={unowned}m",
            )
        )
    for ref in set(state.unowned_since) - set(current.items):
        state.unowned_since.pop(ref, None)
    return lines + _clear(state, live, "unowned-item")


def inbox_lines(current: FleetSnapshot, state: DeltaState) -> list[str]:
    """Envelopes addressed to this session that it has not acknowledged.

    Unread is a level rather than an edge. An envelope already waiting
    when the watch arms is exactly what the reader needs told first, so
    this fires on the arming pass — where no comparison is possible —
    and then once per state change, never once per pass.

    An envelope leaving the unread set needs no line: acknowledging it
    was the reader's own action, so a clear would only be noise.
    """
    lines: list[str] = []
    live: set[str] = set()
    for key in sorted(current.envelopes):
        row = current.envelopes[key]
        if row.recipient_session_id != current.self_session_id:
            continue
        if row.state not in UNREAD_STATES:
            continue
        inbox_key = f"inbox:{identifier(row.message_id)} state={row.state}"
        live.add(inbox_key)
        lines.extend(
            _raise_once(
                state,
                inbox_key,
                f"{LINE_PREFIX} inbox {identifier(row.message_id)} "
                f"state={row.state} from={identifier(row.sender_session_id)}",
            )
        )
    stale = {key for key in state.active_alarms if key.startswith("inbox:")} - live
    state.active_alarms -= stale
    return lines


def _starved_minutes(row: EnvelopeRow, current: FleetSnapshot) -> int | None:
    """Minutes an envelope has been starved, or ``None`` if it is fine."""
    if row.state != "pending" or row.injection_count:
        return None
    waiting = minutes_since(row.created_at, current.taken_at)
    if waiting is None or waiting < STARVED_ENVELOPE_MINUTES:
        return None
    recipient = current.sessions.get(row.recipient_session_id)
    if recipient is None or recipient.lifecycle != "live":
        # An envelope to a session that ended before injection stays
        # pending forever; reporting it every pass as a live starved
        # worker is the false alarm this exclusion exists to stop.
        return None
    if (
        recipient.activity_at is not None
        and row.created_at is not None
        and recipient.activity_at > row.created_at
    ):
        return None
    return waiting


def starved_envelope_alarms(current: FleetSnapshot, state: DeltaState) -> list[str]:
    """Undelivered envelopes whose recipient has gone quiet since the send."""
    lines: list[str] = []
    live: set[str] = set()
    for key in sorted(current.envelopes):
        row = current.envelopes[key]
        waiting = _starved_minutes(row, current)
        if waiting is None:
            continue
        alarm_key = (
            f"starved-envelope:message={identifier(row.message_id)} "
            f"recipient={identifier(row.recipient_session_id)}"
        )
        live.add(alarm_key)
        lines.extend(
            _raise_once(
                state,
                alarm_key,
                f"{LINE_PREFIX} ALARM starved-envelope "
                f"message={identifier(row.message_id)} "
                f"recipient={identifier(row.recipient_session_id)} "
                f"pending={waiting}m injections=0 "
                f"reach={address_recipe(row.recipient_session_id, current)!r}",
            )
        )
    return lines + _clear(state, live, "starved-envelope")


__all__ = [
    "BACKLOG_STATUSES",
    "DeltaState",
    "IDLE_HOLDER_MINUTES",
    "LINE_PREFIX",
    "STARVED_ENVELOPE_MINUTES",
    "UNOWNED_ITEM_MINUTES",
    "UNREAD_STATES",
    "address_recipe",
    "identifier",
    "idle_holder_alarms",
    "inbox_lines",
    "minutes_since",
    "starved_envelope_alarms",
    "unowned_item_alarms",
]
