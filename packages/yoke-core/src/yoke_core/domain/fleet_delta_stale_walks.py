"""Alarm when a QA walk stops heartbeating before the stale sweep aborts it.

The sweep aborts an ``active`` or ``walking`` execution whose heartbeat is 30
minutes old unless its live owner is parked, and the next waiter then takes
and resets the host. The roster serves each session's heartbeat-governed walks
(``silent_walks``); one silent past the owner-mail line raises one
``fleet ALARM stale-walk`` line and clears once it heartbeats or ends.

An owner that already has an idle-holder line carries the walk there as
``stale_walk=<id>:<N>m`` instead, so one silence is one line. The separate
line remains for an owner making tool calls while its walk does not heartbeat,
which idle-holder never flags.
"""

from __future__ import annotations

from datetime import datetime

from yoke_core.domain.fleet_delta_alarms import (
    LINE_PREFIX,
    DeltaState,
    _clear,
    _raise_once,
    identifier,
    idle_holder_candidates,
)
from yoke_core.domain.fleet_delta_snapshot import FleetSnapshot, SessionRow, WalkRow
from yoke_core.domain.qa_plan_execution_silence_notice import SILENT_WALK_WARN_SECONDS

_FOLDED = "stale-walk-folded"


def idle_holder_rows(current: FleetSnapshot) -> list[SessionRow]:
    """Idle-holder candidates with no landing or dependency wait: those that alarm.

    Both detectors read it: idle-holder raises these rows, and a stale walk
    whose owner is one of them folds into that line.
    """
    return [
        row
        for row in idle_holder_candidates(current)
        if not any(
            ref in current.landing_waits or ref in row.dependency_waits
            for ref in row.claimed_items
        )
    ]


def stale_walks(row: SessionRow, now: datetime) -> list[tuple[WalkRow, int]]:
    """This live, unparked owner's walks silent past the warning line."""
    if row.lifecycle != "live" or row.parked:
        return []
    found: list[tuple[WalkRow, int]] = []
    for walk in row.walks:
        if walk.heartbeat_at is None:
            continue
        silent = (now - walk.heartbeat_at).total_seconds()
        if silent >= SILENT_WALK_WARN_SECONDS:
            found.append((walk, int(silent // 60)))
    return found


def stale_walk_suffix(row: SessionRow, now: datetime) -> str:
    """The idle-holder line's ``stale_walk=`` field, or empty."""
    walks = stale_walks(row, now)
    if not walks:
        return ""
    return " stale_walk=" + ",".join(
        f"{walk.execution_id}:{minutes}m" for walk, minutes in walks
    )


def stale_walk_alarms(current: FleetSnapshot, state: DeltaState) -> list[str]:
    """One line per silent walk whose owner has no idle-holder line.

    Runs before :func:`idle_holder_alarms`: a walk newly folded into an
    idle-holder line resets that line's repeat clock so it is reprinted with
    ``stale_walk=`` this pass, not an hour later. A walk already alarming on
    its own line keeps that line until it clears.
    """
    idle = {row.session_id for row in idle_holder_rows(current)}
    lines: list[str] = []
    live: set[str] = set()
    folded: set[str] = set()
    for session_id, row in sorted(current.sessions.items()):
        for walk, minutes in stale_walks(row, current.taken_at):
            key = f"stale-walk:execution={walk.execution_id}"
            if session_id in idle and key not in state.active_alarms:
                fold = f"{_FOLDED}:execution={walk.execution_id}"
                folded.add(fold)
                if fold not in state.active_alarms:
                    state.active_alarms.add(fold)
                    state.raised_at.pop(
                        f"idle-holder:session={identifier(session_id)}", None
                    )
                continue
            live.add(key)
            lines.extend(
                _raise_once(
                    state,
                    key,
                    f"{LINE_PREFIX} ALARM stale-walk "
                    f"execution={walk.execution_id} item={walk.item} "
                    f"host={walk.test_machine} silent={minutes}m "
                    f"session={identifier(session_id)}",
                )
            )
    state.active_alarms -= {
        key
        for key in state.active_alarms
        if key.startswith(f"{_FOLDED}:") and key not in folded
    }
    return lines + _clear(state, live, "stale-walk")


__all__ = [
    "idle_holder_rows",
    "stale_walk_alarms",
    "stale_walk_suffix",
    "stale_walks",
]
