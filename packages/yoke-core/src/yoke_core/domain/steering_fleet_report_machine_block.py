"""One machine block per machine id, shared by every scope in a report.

Machines are not a scope's property: two seats running on the same box see
the same lanes, the same plan meters and the same relay. So the combined
report renders each machine once, after the scope sections, from whichever
reports carry facts about it — keyed by machine id rather than by
comparing rendered text.
"""

from __future__ import annotations

from typing import Sequence
from dataclasses import replace

from yoke_core.domain import steering_fleet_plan_capacity as _plan_limits
from yoke_core.domain.session_launch_capacity import MachineCapacity
from yoke_core.domain.steering_fleet_report import FleetReport
from yoke_core.domain.steering_fleet_report_balance import aggregate_session_counts, launch_balance_lines
from yoke_core.domain.steering_fleet_report_test_machines import test_machine_lines
from yoke_core.domain.steering_fleet_report_capacity import (
    SurfaceReadiness,
    capacity_line,
)
from yoke_core.domain.steering_fleet_report_limits import MachinePlanLimit
from yoke_core.domain.steering_fleet_report_native_models import native_model_lines
from yoke_core.domain.steering_fleet_report_relay_health import relay_health_lines
from yoke_core.domain.steering_fleet_report_render import launchable_line


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
        for entry in report.native_models:
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
    """One block per machine_id: launchable pairs, capacity, plan limits."""
    machine_ids = _distinct_machine_ids(reports)
    if not machine_ids:
        return [launchable_line(())]
    names = {
        machine_id: name
        for report in reports
        for machine_id, name in report.machine_names
    }
    lines: list[str] = []
    counts = aggregate_session_counts(_project_reports(reports))
    for index, machine_id in enumerate(machine_ids):
        if index:
            lines.append("")
        ready = _machine_launchable(reports, machine_id)
        lines.append(launchable_line(ready, machine_names=names))
        capacity = _machine_capacity(reports, machine_id)
        if capacity is not None:
            lines.append(f"  {capacity_line(capacity)}")
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
                with_legend=False,
                session_counts=tuple(
                    row for row in counts if row.machine_id == machine_id
                ),
            )
        )
        lines.extend(
            native_model_lines(
                tuple({
                    (row.machine_id, row.surface): row
                    for report in reports
                    for row in report.native_models
                    if row.machine_id == machine_id
                }.values())
            )
        )
    if any(report.plan_limits for report in reports):
        lines.append(_plan_limits.HEADROOM_LEGEND)
    return lines


def _project_reports(reports: Sequence[FleetReport]) -> tuple[FleetReport, ...]:
    """Counts are project-wide, so document seats must not add them again."""
    by_project = {}
    for report in reports:
        by_project.setdefault(report.project_id, report)
    return tuple(by_project.values())


def fleet_shared_lines(reports: Sequence[FleetReport]) -> list[str]:
    """Test hosts and launch balance once, with counts from each project once."""
    if not reports:
        return []
    projects = _project_reports(reports)
    origins = {}
    for report in projects:
        for name, count in report.origin_counts:
            origins[name] = origins.get(name, 0) + count
    balance = replace(projects[0],
        session_counts=aggregate_session_counts(projects),
        launchable=tuple({(row.machine_id, row.surface): row for report in projects
                          for row in report.launchable}.values()),
        origin_counts=tuple(sorted(origins.items())),
        machine_names=tuple(dict(row for report in projects for row in report.machine_names).items()),
    )
    hosts = tuple(dict.fromkeys(row for report in projects for row in report.test_machines))
    return [*test_machine_lines(hosts), *launch_balance_lines(balance, with_capacity=False)]


__all__ = ["machine_shared_lines", "fleet_shared_lines"]
