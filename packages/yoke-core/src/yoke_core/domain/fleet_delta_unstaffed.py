"""Urgent alarm when runnable unclaimed work sits past the staffing threshold.

The available set and the threshold belong to the fleet report. This detector
reads the clocks charge.schedule already attaches from that same read, emits
one line per waiting episode, and repeats only after another staffing
interval. A launch in flight is staffing, so it does not alarm.
"""

from __future__ import annotations

from yoke_core.domain.fleet_delta_alarms import LINE_PREFIX, DeltaState, _clear
from yoke_core.domain.fleet_delta_snapshot import FleetSnapshot, ItemRow
from yoke_core.domain.session_launch_mandate import item_entrypoint
from yoke_core.domain.steering_fleet_report_available import is_unstaffed_ready
from yoke_core.domain.steering_fleet_report_detectors import age_seconds


def staffing_reach(project: str, ref: str) -> str:
    """Stage-level launch create, the command that staffs this item.

    Omitting ``--level`` uses the item's stage level. A judged level still
    goes through ``yoke session-control launch preview`` before create.
    """
    return (
        "yoke session-control launch create "
        f"--project {project} --item {ref} "
        f'--idempotency-key "steer:{project}:{ref}" --json'
    )


def _overdue(row: ItemRow, now) -> int | None:
    """Waiting seconds when this row is the report's overdue available set."""
    if (
        not row.runnable
        or row.claim_state != "unclaimed"
        or not row.next_step
        or row.next_step == "wait"
        or row.pickable_since is None
        or row.staffing_after_seconds <= 0
    ):
        return None
    waiting = age_seconds(row.pickable_since, now) or 0
    if not is_unstaffed_ready(row.launch_state, waiting, row.staffing_after_seconds):
        return None
    return waiting


def unstaffed_ready_alarms(current: FleetSnapshot, state: DeltaState) -> list[str]:
    """One alarm per unstaffed episode, then again after the staffing interval."""
    lines: list[str] = []
    live: set[str] = set()
    live_refs: set[str] = set()
    for ref in sorted(current.items):
        row = current.items[ref]
        waiting = _overdue(row, current.taken_at)
        if waiting is None:
            continue
        key = f"unstaffed-ready:item={ref}"
        live.add(key)
        live_refs.add(ref)
        last = state.unstaffed_emitted_at.get(ref)
        if (
            last is not None
            and (current.taken_at - last).total_seconds() < row.staffing_after_seconds
        ):
            continue
        state.unstaffed_emitted_at[ref] = current.taken_at
        state.active_alarms.add(key)
        command = (
            staffing_reach(row.project, ref)
            if row.project
            else item_entrypoint(row.next_step, ref) or staffing_reach(row.project, ref)
        )
        lines.append(
            f"{LINE_PREFIX} ALARM unstaffed-ready "
            f"item={ref} project={row.project} waiting={waiting // 60}m "
            f"rank={row.rank} next={row.next_step} reach={command!r}"
        )
    for ref in list(state.unstaffed_emitted_at):
        if ref not in live_refs:
            state.unstaffed_emitted_at.pop(ref, None)
    return lines + _clear(state, live, "unstaffed-ready")


__all__ = ["staffing_reach", "unstaffed_ready_alarms"]
