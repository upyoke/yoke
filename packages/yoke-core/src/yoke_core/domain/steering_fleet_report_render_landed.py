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
    from yoke_core.domain.steering_fleet_report_project_rows import ProjectRows


def landed_lines(rows: ProjectRows, *, idle_after_seconds: int) -> list[str]:
    """A declared delivery wait costs one short line, regardless of tool silence.

    Items a listed run is already delivering are that run's members and are
    not repeated here.
    """
    troubled_runs = {run.run_id for run in rows.deployment_runs if run.needs_action}
    visible = rows.visible_landed()
    lines = []
    for entry in visible[:SECTION_LIMIT]:
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
            f"{holder_phrase(entry, idle_after_seconds=idle_after_seconds)}  "
            f"{custody_phrase(entry)}"
        )
        recovery = landed_recovery(entry, idle_after_seconds=idle_after_seconds)
        if recovery:
            line += f"  {recovery}"
        lines.append(line)
    return capped(lines, len(visible))
