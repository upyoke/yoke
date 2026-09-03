"""The line for a worker the model provider stopped.

Two facts have to survive being read quickly. The first is that this is
not the worker's doing, so the line leads with the provider's own words
rather than with anything about the item. The second is whether the seat
is on the hook: a session inside its backoff is already being handled,
and reading it as work is how a seat learns to skim the whole section —
including the rows where nobody is coming.
"""

from __future__ import annotations

from yoke_core.domain.steering_fleet_report import FleetReport
from yoke_core.domain.steering_fleet_report_render_text import (
    SECTION_LIMIT,
    capped,
    minutes,
)
from yoke_core.domain.steering_fleet_report_vendor_errors import VendorErrorSession


#: Longest provider message rendered inline. The classification carries the
#: meaning; the raw text is there to be recognized, and a full stack of URL
#: and payload pushes every other fact on the line out of view.
MESSAGE_LIMIT = 80


def _said(message: str) -> str:
    collapsed = " ".join(message.split())
    if len(collapsed) <= MESSAGE_LIMIT:
        return collapsed
    return collapsed[: MESSAGE_LIMIT - 1] + "…"


def _next_actor(entry: VendorErrorSession) -> str:
    """What happens next for this session, and who does it."""
    attempt = entry.attempts + 1
    if entry.status == "due":
        return f"relay resumes it this poll (attempt {attempt} of {entry.budget})"
    if entry.status == "waiting_backoff":
        return (
            f"relay resumes it at {entry.due_at} "
            f"(attempt {attempt} of {entry.budget})"
        )
    if entry.status == "turn_in_flight":
        return "working now, inside an unreturned tool call — no resume"
    if entry.status == "budget_spent":
        return (
            f"{entry.attempts} resumes spent and it stopped again each time "
            "— yours: check the lane, then wake or reclaim"
        )
    return f"{entry.reason} — yours: no retry can move this"


def vendor_error_lines(report: FleetReport) -> list[str]:
    lines = [
        f"  {entry.public_ref or 'no item'}  session {entry.session_id}  "
        f"{entry.executor_surface or 'unknown surface'} "
        f"{entry.executor_version or 'unknown version'}  "
        f"{entry.signature_id}: {_said(entry.error_message)}  "
        f"stopped {minutes(entry.stopped_seconds)} ago  {_next_actor(entry)}"
        for entry in report.vendor_errors[:SECTION_LIMIT]
    ]
    return capped(lines, len(report.vendor_errors))


__all__ = ["MESSAGE_LIMIT", "vendor_error_lines"]
