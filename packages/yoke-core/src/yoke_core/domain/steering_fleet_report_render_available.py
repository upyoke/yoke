"""How available work reads on the fleet report.

Unstaffed rows keep the waiting clock and the overdue mark. A launch already
in ``assigned``, ``launching``, or ``awaiting_registration`` is staffing in
flight: same section (hiding it would stall a frozen worker), different
label, clock from the launch, no staff-these mark.
"""

from __future__ import annotations

from yoke_core.domain.steering_fleet_report import FleetReport
from yoke_core.domain.steering_fleet_report_available import FrontierEntry
from yoke_core.domain.steering_fleet_report_render_text import (
    OVERDUE_MARK,
    SECTION_LIMIT,
    capped,
    minutes,
)


def available_heading(report: FleetReport) -> str:
    staffing = minutes(report.staffing_after_seconds)
    return (
        f"available — runnable and unclaimed, staff these "
        f"({OVERDUE_MARK} waiting over {staffing}; "
        f"new = never started, stopped = owner released; "
        f"launch = staffing in flight, clock from the launch):"
    )


def available_lines(report: FleetReport) -> list[str]:
    now = report.composed_at
    overdue = {entry.item_id for entry in report.waited_too_long()}
    lines = [
        _available_row(entry, now, overdue)
        for entry in report.available[:SECTION_LIMIT]
    ]
    return capped(lines, len(report.available))


def _available_row(
    entry: FrontierEntry, now: str, overdue: set[int]
) -> str:
    mark = OVERDUE_MARK if entry.item_id in overdue else " "
    if entry.launch_state:
        kind = f"launch {entry.launch_state}"
        clock = f"in flight {minutes(entry.waiting_seconds(now))}"
    else:
        kind = "stopped" if entry.was_owned else "new"
        clock = f"waiting {minutes(entry.waiting_seconds(now))}"
    return (
        f"  {mark} {entry.public_ref}  "
        f"rank {entry.rank}  next {entry.next_step}  "
        f"{kind}  {clock}  {entry.title}"
    )


__all__ = ["available_heading", "available_lines"]
