"""Differences between two fleet observations, one line each.

Deltas include an item changing status or ownership and a session registering
or ending. Those edges need a previous observation. Available work and the
level conditions in :mod:`yoke_core.domain.fleet_delta_alarms` also fire on
the arming pass, so existing actionable work needs no subsequent change.

Silence is the contract: when nothing moved, this module returns an
empty list. The probe checks due steering reports independently.
"""

from __future__ import annotations

from yoke_core.domain.fleet_delta_alarms import (
    DeltaState,
    LINE_PREFIX,
    identifier,
    idle_holder_alarms,
    inbox_lines,
    starved_envelope_alarms,
    unowned_item_alarms,
)
from yoke_core.domain.fleet_delta_snapshot import FleetSnapshot


def item_deltas(previous: FleetSnapshot | None, current: FleetSnapshot) -> list[str]:
    """Availability, status, ownership, and frontier membership changes."""
    lines: list[str] = []
    for ref in sorted(current.items):
        now_row = current.items[ref]
        was = previous.items.get(ref) if previous is not None else None
        if now_row.available and (was is None or not was.available):
            lines.append(
                f"{LINE_PREFIX} item {ref} available status={now_row.status} "
                f"claim={now_row.claim_state}"
            )
        if previous is None:
            continue
        if was is None:
            lines.append(
                f"{LINE_PREFIX} item {ref} entered status={now_row.status} "
                f"claim={now_row.claim_state}"
            )
            continue
        if was.status != now_row.status:
            lines.append(
                f"{LINE_PREFIX} item {ref} status {was.status} -> {now_row.status}"
            )
        if was.claim_state != now_row.claim_state:
            lines.append(
                f"{LINE_PREFIX} item {ref} claim {was.claim_state} -> "
                f"{now_row.claim_state}"
            )
    for ref in sorted(set(previous.items if previous else ()) - set(current.items)):
        lines.append(
            f"{LINE_PREFIX} item {ref} left-frontier last-status="
            f"{previous.items[ref].status}"
        )
    return lines


def session_deltas(previous: FleetSnapshot, current: FleetSnapshot) -> list[str]:
    """Registration, ending, and termination across the roster."""
    lines: list[str] = []
    for session_id in sorted(current.sessions):
        row = current.sessions[session_id]
        was = previous.sessions.get(session_id)
        if was is None:
            lines.append(
                f"{LINE_PREFIX} session {identifier(session_id)} registered "
                f"surface={row.executor_surface} mode={row.mode or 'none'}"
            )
            continue
        if was.lifecycle != row.lifecycle and row.lifecycle != "live":
            lines.append(
                f"{LINE_PREFIX} session {identifier(session_id)} "
                f"{row.lifecycle} surface={row.executor_surface}"
            )
    return lines


def compare(
    previous: FleetSnapshot | None,
    current: FleetSnapshot,
    state: DeltaState,
) -> list[str]:
    """Return every line this pass should emit, in reading order."""
    lines: list[str] = []
    lines.extend(inbox_lines(current, state))
    lines.extend(item_deltas(previous, current))
    if previous is not None:
        lines.extend(session_deltas(previous, current))
    lines.extend(idle_holder_alarms(current, state))
    lines.extend(unowned_item_alarms(current, state))
    lines.extend(starved_envelope_alarms(current, state))
    return lines


def error_line(function_id: str, detail: str, attempt: int, limit: int) -> str:
    """A named transient read failure the reader can act on."""
    return (
        f"{LINE_PREFIX} ERROR read failed {function_id}: {detail} "
        f"(attempt {attempt}/{limit}; retrying)"
    )


def fatal_line(function_id: str, detail: str, limit: int) -> str:
    """A give-up line naming the failure and the operator's next step."""
    return (
        f"{LINE_PREFIX} FATAL read failed {function_id}: {detail} "
        f"({limit} consecutive failures; stopping). Check the active "
        f"connection with `yoke env list`, then re-arm `yoke watch fleet`."
    )


__all__ = [
    "compare",
    "error_line",
    "fatal_line",
    "item_deltas",
    "session_deltas",
]
