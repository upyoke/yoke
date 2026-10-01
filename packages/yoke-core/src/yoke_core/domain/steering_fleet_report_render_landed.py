"""Compact expected delivery waits; keep recovery detail on actionable landings."""

from __future__ import annotations

from typing import TYPE_CHECKING

from yoke_core.domain.delivery_landing_custody import HELD
from yoke_core.domain.steering_fleet_report_landed_open import (
    custody_phrase,
    holder_phrase,
    landed_recovery,
)
from yoke_core.domain.steering_fleet_report_render_text import (
    SECTION_LIMIT,
    capped,
    minutes,
)

if TYPE_CHECKING:
    from yoke_core.domain.steering_fleet_report import FleetReport


def landed_lines(report: FleetReport) -> list[str]:
    """A declared delivery wait costs one short line, regardless of tool silence."""
    troubled_runs = {run.run_id for run in report.deployment_runs if run.needs_action}
    lines = []
    for entry in report.landed_open[:SECTION_LIMIT]:
        if entry.delivery_wait and entry.custody_run_id not in troubled_runs:
            delivery = (
                f"delivering in {entry.custody_run_id}"
                if entry.custody_state == HELD
                else "awaiting deployment run"
            )
            lines.append(f"  {entry.public_ref}  {delivery} (parked)")
            continue
        line = (
            f"  {entry.public_ref}  still {entry.status}  "
            f"landed {minutes(entry.landed_seconds)} ago  "
            f"{holder_phrase(entry, idle_after_seconds=report.idle_after_seconds)}  "
            f"{custody_phrase(entry)}"
        )
        recovery = landed_recovery(entry, idle_after_seconds=report.idle_after_seconds)
        if recovery:
            line += f"  {recovery}"
        lines.append(line)
    return capped(lines, len(report.landed_open))
