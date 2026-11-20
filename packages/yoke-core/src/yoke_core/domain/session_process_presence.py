"""Durable evidence that a native process returned after a recorded death."""

from datetime import datetime
from typing import Any, Mapping

from yoke_core.domain.session_reclaim_progress import parse_stamp


def activity_supersedes_process_death(
    row: Mapping[str, Any], death: datetime
) -> bool:
    """Only activity strictly after death proves that the process returned."""
    completed = parse_stamp(row.get("last_tool_call_at") or None)
    if completed is not None and completed > death:
        return True
    # The turn-end relay can stamp waiting without a live process.
    running = (
        parse_stamp(row.get("turn_posture_at") or None)
        if row.get("turn_posture") == "running"
        else None
    )
    return running is not None and running > death
