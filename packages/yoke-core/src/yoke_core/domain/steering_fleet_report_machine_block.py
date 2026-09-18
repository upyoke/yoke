"""One machine block per machine id, shared by every scope in a report.

Machines are not a scope's property: two seats running on the same box see
the same lanes, the same plan meters and the same relay. So the combined
report renders each machine once, after the scope sections, from whichever
reports carry facts about it — keyed by machine id rather than by
comparing rendered text.
"""

from __future__ import annotations

from typing import Sequence

from yoke_core.domain import steering_fleet_plan_capacity as _plan_limits
from yoke_core.domain.session_launch_capacity import MachineCapacity
from yoke_core.domain.steering_fleet_report import FleetReport
from yoke_core.domain.steering_fleet_report_balance import aggregate_session_counts
from yoke_core.domain.steering_fleet_report_capacity import (
    SurfaceReadiness,
    capacity_line,
)
from yoke_core.domain.steering_fleet_report_limits import MachinePlanLimit
from yoke_core.domain.steering_fleet_report_native_models import native_model_lines
from yoke_core.domain.steering_fleet_report_relay_health import relay_health_lines
from yoke_core.domain.steering_fleet_report_render import (
    LAUNCH_BALANCE_NOTE,
    launchable_line,
)


def _distinct_machine_ids(reports: Sequence[FleetReport]) -> list[str]:
    ids: set[str] = set()
    for report in reports:
        for ready in report.launchable:
            ids.add(ready.machine_id)
        for row in report.plan_limits:
            ids.add(row.machine_id)
        for entry in report.machine_capacity:
            ids.add(entry.machine_id)
        for entry in report.relay_health:
            ids.add(entry.machine_id)
    return sorted(ids)


def _machine_capacity(
    reports: Sequence[FleetReport], machine_id: str
) -> MachineCapacity | None:
    for report in reports:
        for entry in report.machine_capacity:
            if entry.machine_id == machine_id:
                return entry
    return None


def _machine_launchable(
    reports: Sequence[FleetReport], machine_id: str
) -> list[SurfaceReadiness]:
    seen: set[str] = set()
    ready: list[SurfaceReadiness] = []
    for report in reports:
        for item in report.launchable:
            if item.machine_id == machine_id and item.surface not in seen:
                seen.add(item.surface)
                ready.append(item)
    ready.sort(key=lambda item: item.surface)
    return ready


def _machine_plan_limits(
    reports: Sequence[FleetReport], machine_id: str
) -> tuple[MachinePlanLimit, ...]:
    seen: dict[tuple[str, str, str, str, str], MachinePlanLimit] = {}
    for report in reports:
        for row in report.plan_limits:
            if row.machine_id != machine_id:
                continue
            key = (
                row.machine_name,
                row.surface,
                row.window_kind,
                row.scope,
                row.meter,
            )
            seen.setdefault(key, row)
    return tuple(seen.values())


def machine_shared_lines(reports: Sequence[FleetReport], *, now: str) -> list[str]:
    """One block per machine_id: launchable pairs, capacity, note, plan limits."""
    machine_ids = _distinct_machine_ids(reports)
    if not machine_ids:
        return [launchable_line(())]
    names = {
        machine_id: name
        for report in reports
        for machine_id, name in report.machine_names
    }
    lines: list[str] = []
    counts = aggregate_session_counts(reports)
    for index, machine_id in enumerate(machine_ids):
        if index:
            lines.append("")
        ready = _machine_launchable(reports, machine_id)
        lines.append(launchable_line(ready, machine_names=names))
        capacity = _machine_capacity(reports, machine_id)
        if capacity is not None:
            lines.append(f"  {capacity_line(capacity)}")
        if ready:
            lines.append(f"  {LAUNCH_BALANCE_NOTE}")
        conditions_by_relay = {
            entry.relay_id: entry
            for report in reports
            for entry in report.relay_health
            if entry.machine_id == machine_id
        }
        conditions = tuple(conditions_by_relay.values())
        lines.extend(relay_health_lines(conditions, machine_id=machine_id))
        lines.extend(
            _plan_limits.plan_limit_lines(
                _machine_plan_limits(reports, machine_id),
                now=now,
                session_counts=tuple(
                    row for row in counts if row.machine_id == machine_id
                ),
            )
        )
        lines.extend(
            native_model_lines(
                tuple(
                    row
                    for report in reports
                    for row in report.native_models
                    if row.machine_id == machine_id
                )
            )
        )
    return lines


__all__ = ["machine_shared_lines"]
