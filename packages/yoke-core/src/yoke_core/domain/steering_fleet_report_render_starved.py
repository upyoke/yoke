"""The line for an envelope its recipient has not read.

Starvation is the section where the same visible symptom — nothing
delivered — has several different causes, and telling them apart is the
whole value of the line. A plane that never tried, one whose every
attempt refused for a nameable reason, one already escalated to a wake,
one that only a person typing in a desktop chat can feed, and one whose
recipient is simply busy inside a tool call all read as "not delivered"
and want five different responses from the seat.
"""

from __future__ import annotations

from yoke_contracts.session_control.evidence_fetch import evidence_pull_suffix
from yoke_core.domain.steering_fleet_report import FleetReport, StarvedDelivery
from yoke_core.domain.steering_fleet_report_render_text import (
    SECTION_LIMIT,
    capped,
    minutes,
)


def starved_line(entry: StarvedDelivery) -> str:
    # A recipient inside an unreturned tool call is working, and its
    # envelope lands on that call's own hook. That is the whole finding —
    # nothing is owed, nothing failed, and the seat should not resume it —
    # so it replaces the rest of the line rather than decorating it.
    if entry.turn_in_flight_since:
        return (
            f"  session {entry.session_id}  {entry.envelope_count} envelope(s), "
            f"oldest {minutes(entry.oldest_seconds)}, recipient turn in "
            f"flight since {entry.turn_in_flight_since} — waits for that "
            "call's hook, no resume"
        )
    # An already-escalated recipient is a wake in flight, not one the seat
    # still owes by hand, so the line says which absence authorized it. A
    # desktop recipient is neither: Yoke never resumes one, so the line asks
    # for the only thing that delivers it instead of naming a revive recipe.
    if entry.operator_wake:
        suffix = (
            ", waiting for the operator to wake it — ask them to type "
            "anything in that chat"
        )
    else:
        suffix = (
            f", wake escalated ({entry.wake_escalation})"
            if entry.wake_escalation
            else ""
        )
    # What was tried, and how it ended. A seat reading "never injected" with
    # nothing else cannot tell a plane that made no attempt from one whose
    # every attempt refused for the same nameable reason, and both shapes
    # ran unread on one machine for two hours.
    if entry.diagnostic:
        tried = f", last attempt failed ({entry.diagnostic})"
    elif entry.attempt_count == 0:
        tried = ", no delivery attempted"
    else:
        tried = ""
    return (
        f"  session {entry.session_id}  {entry.envelope_count} envelope(s), "
        f"oldest {minutes(entry.oldest_seconds)}, never injected"
        f"{tried}{suffix}{evidence_pull_suffix(entry.session_id, entry.evidence_id)}"
    )


def starved_lines(report: FleetReport) -> list[str]:
    lines = [starved_line(entry) for entry in report.starved[:SECTION_LIMIT]]
    return capped(lines, len(report.starved))


__all__ = ["starved_line", "starved_lines"]
