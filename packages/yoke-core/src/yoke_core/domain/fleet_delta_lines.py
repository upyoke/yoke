"""Differences between two fleet observations, one line each.

Deltas are edges: an item changed status or ownership, a session
registered or ended. Every one of them needs a previous observation to
compare against, so the arming pass emits none — only the level
conditions in :mod:`yoke_core.domain.fleet_delta_alarms`, which
:func:`compare` folds in here, can fire that early.

Silence is the contract: when nothing moved, this module returns an
empty list and the probe prints nothing.
"""

from __future__ import annotations

from yoke_core.domain.fleet_delta_alarms import (
    DeltaState,
    LINE_PREFIX,
    idle_holder_alarms,
    inbox_lines,
    short,
    starved_envelope_alarms,
    unowned_item_alarms,
)
from yoke_core.domain.fleet_delta_snapshot import FleetSnapshot


def item_deltas(previous: FleetSnapshot, current: FleetSnapshot) -> list[str]:
    """Status, ownership, and frontier membership changes between passes."""
    lines: list[str] = []
    for ref in sorted(current.items):
        now_row = current.items[ref]
        was = previous.items.get(ref)
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
    for ref in sorted(set(previous.items) - set(current.items)):
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
                f"{LINE_PREFIX} session {short(session_id)} registered "
                f"surface={row.executor_surface} mode={row.mode or 'none'}"
            )
            continue
        if was.lifecycle != row.lifecycle and row.lifecycle != "live":
            lines.append(
                f"{LINE_PREFIX} session {short(session_id)} {row.lifecycle} "
                f"surface={row.executor_surface}"
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
    if previous is not None:
        lines.extend(item_deltas(previous, current))
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
