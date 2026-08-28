"""Turn one fleet report into the text a steerer reads and the JSON it queries.

Kept apart from composition because the two change for different reasons: a
new detector is a query, a clearer report is wording. The text form leads with
what needs a decision and puts the standing picture underneath, so a steerer
who reads only the first lines still learns the part that was invisible.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.steering_fleet_report import (
    ClaimHolder,
    FleetReport,
    FrontierEntry,
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


def report_dict(report: FleetReport) -> dict[str, Any]:
    """The machine-readable projection of one report."""
    now = report.composed_at
    return {
        "project_id": report.project_id,
        "composed_at": now,
        "stale_after_seconds": report.stale_after_seconds,
        "actionable": report.actionable,
        "fingerprint": report.fingerprint(),
        "frontier": [_entry_dict(entry, now) for entry in report.frontier],
        "unstaffed": [_entry_dict(entry, now) for entry in report.unstaffed],
        "unowned": [_entry_dict(entry, now) for entry in report.unowned],
        "holders": [_holder_dict(holder) for holder in report.holders],
        "idle": [_holder_dict(holder) for holder in report.idle],
        "launchable": [
            {"machine_id": ready.machine_id, "surface": ready.surface}
            for ready in report.launchable
        ],
    }


def _entry_lines(
    entries: tuple[FrontierEntry, ...],
    *,
    now: str,
) -> list[str]:
    lines = [
        f"  {entry.item_ref}  rank {entry.rank}  next {entry.next_step}  "
        f"waiting {_minutes(entry.waiting_seconds(now))}  {entry.title}"
        for entry in entries[:SECTION_LIMIT]
    ]
    if len(entries) > SECTION_LIMIT:
        lines.append(f"  ... {len(entries) - SECTION_LIMIT} more")
    return lines


def _holder_lines(holders: tuple[ClaimHolder, ...]) -> list[str]:
    lines = [
        f"  {holder.item_ref}  session {holder.session_id}  mode "
        f"{holder.mode or 'unset'}  quiet {_minutes(holder.idle_seconds)}"
        for holder in holders[:SECTION_LIMIT]
    ]
    if len(holders) > SECTION_LIMIT:
        lines.append(f"  ... {len(holders) - SECTION_LIMIT} more")
    return lines


def _section(heading: str, lines: list[str]) -> list[str]:
    if not lines:
        return [f"{heading}: none"]
    return [heading + ":", *lines]


def report_body(report: FleetReport) -> str:
    """The steerer-facing text of one report."""
    now = report.composed_at
    stale = _minutes(report.stale_after_seconds)
    launchable = ", ".join(
        f"{ready.machine_id}/{ready.surface}" for ready in report.launchable
    )
    lines = [
        REPORT_BEGIN,
        f"project {report.project_id} · composed {now} · stale threshold {stale}",
        REPORT_PREAMBLE,
        "",
        *_section(
            f"unstaffed — runnable, never owned, waiting over {stale}",
            _entry_lines(report.unstaffed, now=now),
        ),
        *_section(
            f"unowned — owner released, unclaimed over {stale}",
            _entry_lines(report.unowned, now=now),
        ),
        *_section(
            f"idle holders — claim held, no tool call in over {stale} "
            "(parked sessions excluded; they declared their wait)",
            _holder_lines(report.idle),
        ),
        "",
        *_section(
            "frontier — runnable, unclaimed, not waiting",
            _entry_lines(report.frontier, now=now),
        ),
        *_section("live item claims", _holder_lines(report.holders)),
        f"launchable machine/surface pairs: {launchable or 'none'}",
        REPORT_END,
    ]
    return "\n".join(lines)


__all__ = [
    "REPORT_BEGIN",
    "REPORT_END",
    "REPORT_PREAMBLE",
    "SECTION_LIMIT",
    "report_body",
    "report_dict",
]
