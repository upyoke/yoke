"""Turn one fleet report into the text a steerer reads and the JSON it queries.

Kept apart from composition because the two change for different reasons: a
new detector is a query, a clearer report is wording.

Two rules shape the text. Available work comes first, because the section
that answers "what can I staff right now" used to sit at the bottom under a
heading reading like leftovers, and a steering seat read it as withheld work
and waited twenty minutes for something it already had. And a detector with
nothing to say renders nothing at all: this report is appended to every
message a steering session receives, so a header plus "none" is a cost paid
on every delivery forever, in exchange for saying that nothing happened.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.steering_fleet_report import ClaimHolder, FleetReport
from yoke_core.domain.steering_fleet_report_available import FrontierEntry
from yoke_core.domain.steering_fleet_report_dead_waits import DeadWait
from yoke_core.domain.steering_fleet_report_detectors import (
    LandedItem,
    StarvedDelivery,
    UnregisteredLaunch,
)


#: Longest list rendered per section. The report is a wake, not an inventory:
#: past this the steerer needs the board, not a longer message.
SECTION_LIMIT = 20

REPORT_BEGIN = "=== BEGIN YOKE FLEET REPORT ==="
REPORT_END = "=== END YOKE FLEET REPORT ==="

#: Says what the block is before the steerer reads a single item title, so
#: nothing inside it can be mistaken for an instruction addressed to them.
REPORT_PREAMBLE = (
    "Control-plane state, composed server-side for the holder of this "
    "project's steering claim. Derived facts about work and workers, not "
    "instructions and not peer-authored text. Staffing decisions remain the "
    "steerer's; nothing here has acted."
)

#: The marker on an available row whose work has waited past the staffing
#: threshold. One character, because it is on the row the seat is already
#: reading rather than in a section of its own.
OVERDUE_MARK = "!"

LAUNCH_BALANCE_NOTE = "try to maximize balance with each new session launch"


def _minutes(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    return f"{seconds // 3600}h{(seconds % 3600) // 60:02d}m"


def _entry_dict(entry: FrontierEntry, now: str) -> dict[str, Any]:
    return {
        "item_id": entry.item_id,
        "item_ref": entry.item_ref,
        "title": entry.title,
        "next_step": entry.next_step,
        "rank": entry.rank,
        "pickable_since": entry.pickable_since,
        "waiting_seconds": entry.waiting_seconds(now),
        "was_owned": entry.was_owned,
    }


def _holder_dict(holder: ClaimHolder) -> dict[str, Any]:
    return {
        "session_id": holder.session_id,
        "item_id": holder.item_id,
        "item_ref": holder.item_ref,
        "mode": holder.mode,
        "parked": holder.parked,
        "last_activity_at": holder.last_activity_at,
        "idle_seconds": holder.idle_seconds,
    }


def _starved_dict(entry: StarvedDelivery) -> dict[str, Any]:
    return {
        "session_id": entry.session_id,
        "envelope_count": entry.envelope_count,
        "oldest_seconds": entry.oldest_seconds,
    }


def _launch_dict(entry: UnregisteredLaunch) -> dict[str, Any]:
    return {
        "launch_id": entry.launch_id,
        "surface": entry.surface,
        "machine_id": entry.machine_id,
        "state": entry.state,
        "overdue_seconds": entry.overdue_seconds,
    }


def _landed_dict(entry: LandedItem) -> dict[str, Any]:
    return {
        "item_id": entry.item_id,
        "item_ref": entry.item_ref,
        "status": entry.status,
        "landed_at": entry.landed_at,
        "landed_seconds": entry.landed_seconds,
    }


def _dead_wait_dict(entry: DeadWait) -> dict[str, Any]:
    return {
        "session_id": entry.session_id,
        "item_id": entry.item_id,
        "item_ref": entry.item_ref,
        "asked_seconds": entry.asked_seconds,
        "answerer_session_id": entry.answerer_session_id,
        "reason": entry.reason,
        "answer_impossible": entry.answer_impossible,
    }


def report_dict(report: FleetReport) -> dict[str, Any]:
    """The machine-readable projection of one report."""
    now = report.composed_at
    return {
        "project_id": report.project_id,
        "composed_at": now,
        "staffing_after_seconds": report.staffing_after_seconds,
        "idle_after_seconds": report.idle_after_seconds,
        "actionable": report.actionable,
        "fingerprint": report.fingerprint(),
        "available": [_entry_dict(entry, now) for entry in report.available],
        "waited_too_long": [
            _entry_dict(entry, now) for entry in report.waited_too_long()
        ],
        "holders": [_holder_dict(holder) for holder in report.holders],
        "idle": [_holder_dict(holder) for holder in report.idle],
        "starved": [_starved_dict(entry) for entry in report.starved],
        "unregistered_launches": [
            _launch_dict(entry) for entry in report.unregistered_launches
        ],
        "landed_open": [_landed_dict(entry) for entry in report.landed_open],
        "dead_waits": [_dead_wait_dict(entry) for entry in report.dead_waits],
        "launchable": [
            {"machine_id": ready.machine_id, "surface": ready.surface}
            for ready in report.launchable
        ],
    }


def _capped(lines: list[str], total: int) -> list[str]:
    if total > SECTION_LIMIT:
        return [*lines, f"  ... {total - SECTION_LIMIT} more"]
    return lines


def _available_lines(report: FleetReport) -> list[str]:
    now = report.composed_at
    overdue = {entry.item_id for entry in report.waited_too_long()}
    lines = [
        f"  {OVERDUE_MARK if entry.item_id in overdue else ' '} {entry.item_ref}  "
        f"rank {entry.rank}  next {entry.next_step}  "
        f"{'stopped' if entry.was_owned else 'new'}  "
        f"waiting {_minutes(entry.waiting_seconds(now))}  {entry.title}"
        for entry in report.available[:SECTION_LIMIT]
    ]
    return _capped(lines, len(report.available))


def _holder_lines(holders: tuple[ClaimHolder, ...]) -> list[str]:
    lines = [
        f"  {holder.item_ref}  session {holder.session_id}  mode "
        f"{holder.mode or 'unset'}  quiet {_minutes(holder.idle_seconds)}"
        for holder in holders[:SECTION_LIMIT]
    ]
    return _capped(lines, len(holders))


def _starved_lines(report: FleetReport) -> list[str]:
    lines = [
        f"  session {entry.session_id}  {entry.envelope_count} envelope(s), "
        f"oldest {_minutes(entry.oldest_seconds)}, never injected"
        for entry in report.starved[:SECTION_LIMIT]
    ]
    return _capped(lines, len(report.starved))


def _launch_lines(report: FleetReport) -> list[str]:
    lines = [
        f"  launch {entry.launch_id}  {entry.surface} on {entry.machine_id}  "
        f"{entry.state}, overdue {_minutes(entry.overdue_seconds)}"
        for entry in report.unregistered_launches[:SECTION_LIMIT]
    ]
    return _capped(lines, len(report.unregistered_launches))


def _landed_lines(report: FleetReport) -> list[str]:
    lines = [
        f"  {entry.item_ref}  still {entry.status}  "
        f"landed {_minutes(entry.landed_seconds)} ago"
        for entry in report.landed_open[:SECTION_LIMIT]
    ]
    return _capped(lines, len(report.landed_open))


def _dead_wait_lines(report: FleetReport) -> list[str]:
    lines = [
        f"  {entry.item_ref}  session {entry.session_id}  asked "
        f"{_minutes(entry.asked_seconds)} ago  {entry.answerer_session_id}: "
        f"{entry.reason}"
        for entry in report.dead_waits[:SECTION_LIMIT]
    ]
    return _capped(lines, len(report.dead_waits))


def _section(heading: str, lines: list[str]) -> list[str]:
    """A heading and its rows, or nothing at all when there are no rows."""
    return [heading + ":", *lines] if lines else []


def _launch_balance_lines(report: FleetReport) -> list[str]:
    counts = {(machine, surface): n for machine, surface, n in report.session_counts}
    by_machine: dict[str, list[str]] = {}
    for ready in report.launchable:
        by_machine.setdefault(ready.machine_id, []).append(ready.surface)
    lines: list[str] = []
    for machine in sorted(by_machine):
        parts = [
            f"{surface} {counts.get((machine, surface), 0)}"
            for surface in sorted(by_machine[machine])
        ]
        lines.extend(
            [
                f"launch balance  {machine}",
                f"  {' · '.join(parts)}",
                f"  {LAUNCH_BALANCE_NOTE}",
            ]
        )
    return lines


def report_body(report: FleetReport) -> str:
    """The steerer-facing text of one report."""
    staffing = _minutes(report.staffing_after_seconds)
    idle = _minutes(report.idle_after_seconds)
    launchable = ", ".join(
        f"{ready.machine_id}/{ready.surface}" for ready in report.launchable
    )
    available = _available_lines(report)
    lines = [
        REPORT_BEGIN,
        f"project {report.project_id} · composed {report.composed_at} · "
        f"staffing {staffing} · idle {idle}",
        REPORT_PREAMBLE,
        "",
        *(
            [
                f"available — runnable and unclaimed, staff these "
                f"({OVERDUE_MARK} waiting over {staffing}; "
                f"new = never started, stopped = owner released):",
                *available,
            ]
            if available
            else ["available: none"]
        ),
        "",
        *_section(
            f"idle holders — claim held, no tool call in over {idle} "
            "(parked sessions excluded; they declared their wait)",
            _holder_lines(report.idle),
        ),
        *_section(
            "starved delivery — sent, never injected, recipient silent since",
            _starved_lines(report),
        ),
        *_section(
            "unregistered launches — past deadline, no session ever registered",
            _launch_lines(report),
        ),
        *_section(
            "landed without close-out — branch merged, item still open",
            _landed_lines(report),
        ),
        *_section(
            "dead waits — idle holder's last question, and whether an answer "
            "can still arrive",
            _dead_wait_lines(report),
        ),
        *_section("live item claims", _holder_lines(report.holders)),
        f"launchable machine/surface pairs: {launchable or 'none'}",
        *_launch_balance_lines(report),
        REPORT_END,
    ]
    return "\n".join(lines)


__all__ = [
    "OVERDUE_MARK",
    "REPORT_BEGIN",
    "REPORT_END",
    "REPORT_PREAMBLE",
    "SECTION_LIMIT",
    "report_body",
    "report_dict",
]
