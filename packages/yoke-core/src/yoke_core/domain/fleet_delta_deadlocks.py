"""Alarm when live items wait on each other in a loop of dependencies.

No item in a dependency deadlock can move first, so nothing in it, and
nothing waiting on it, changes again: it is the purest silent failure a
steering pass can miss. ``charge.schedule`` serves each live loop from the
backend detector (:mod:`yoke_core.domain.dependency_cycles`); this detector
raises one line per loop when it appears and clears it when it is broken.
"""

from __future__ import annotations

from yoke_core.domain.dependency_cycles import RECOVERY, DependencyCycle
from yoke_core.domain.fleet_delta_alarms import (
    LINE_PREFIX,
    DeltaState,
    _clear,
    _raise_once,
)
from yoke_core.domain.fleet_delta_snapshot import FleetSnapshot

KIND = "deadlock"


def deadlock_alarms(current: FleetSnapshot, state: DeltaState) -> list[str]:
    """One line per live loop: its edges, the work it strands, the recovery."""
    lines: list[str] = []
    live: set[str] = set()
    for key in sorted(current.deadlocks):
        cycle = DependencyCycle.from_dict(current.deadlocks[key])
        alarm_key = f"{KIND}:{key}"
        live.add(alarm_key)
        lines.extend(
            _raise_once(
                state,
                alarm_key,
                f"{LINE_PREFIX} ALARM {KIND} {cycle.describe()}; recovery: {RECOVERY}",
            )
        )
    return lines + _clear(state, live, KIND)


__all__ = ["deadlock_alarms"]
