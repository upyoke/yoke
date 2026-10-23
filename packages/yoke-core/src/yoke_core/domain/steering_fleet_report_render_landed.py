"""Compact release waits; keep recovery detail on landings that owe close-out."""

from __future__ import annotations

from typing import TYPE_CHECKING

from yoke_core.domain.steering_fleet_report_landed_phrases import (
    delivery_phrase,
    holder_phrase,
    landed_recovery,
    release_wait_phrase,
)
from yoke_core.domain.steering_fleet_report_render_text import (
    SECTION_LIMIT,
    capped,
    minutes,
)

if TYPE_CHECKING:
    from yoke_core.domain.steering_fleet_report_project_rows import ProjectRows


def landed_lines(rows: ProjectRows, *, idle_after_seconds: int) -> list[str]:
    """A landing awaiting its release costs one short line, whoever holds it.

    Items a listed run is already delivering are that run's members and are
    not repeated here.
    """
    troubled_runs = {run.run_id for run in rows.deployment_runs if run.needs_action}
    visible = rows.visible_landed()
    lines = []
    for entry in visible[:SECTION_LIMIT]:
        if entry.awaiting_release and entry.custody_run_id not in troubled_runs:
            lines.append(f"  {entry.public_ref}  {release_wait_phrase(entry)}")
            continue
        line = (
            f"  {entry.public_ref}  still {entry.status}  "
            f"landed {minutes(entry.landed_seconds)} ago  "
            f"{holder_phrase(entry, idle_after_seconds=idle_after_seconds)}  "
            f"{delivery_phrase(entry)}"
        )
        recovery = landed_recovery(entry, idle_after_seconds=idle_after_seconds)
        if recovery:
            line += f"  {recovery}"
        lines.append(line)
    return capped(lines, len(visible))
