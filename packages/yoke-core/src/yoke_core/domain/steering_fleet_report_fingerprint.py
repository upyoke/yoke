"""Content identity for one composed fleet report.

The fingerprint answers "is this the same report I already read", so it is
built from what the sections say and never from how old anything is: ages
advance on every pass, and a fingerprint that moved with them would mark
every report changed and teach the seat to ignore the signal entirely.

That rule is what makes the deployment-run section usable, and it is the
tempting one to break. A stalled run's most striking fact is how long it
has been stalled, so hashing its stage age looks like the way to make the
watcher say so. It is the opposite: the age changes every pass, so the
report would wake the seat once a minute forever and the one pass that
mattered — the one where a verdict turned red — would look like all the
others. Only the run's *state* is hashed: which stage, how many
outstanding of how many, which requirements are red, and which of those
are proven unpassable against the pin (or unproven). The watcher then
fires exactly when one of those changes, and the age is read off the row
once the seat is already looking.

The material is exactly what the hook digest renders, nothing more. A
section the digest does not show — live claims, launch balances, machine
plan limits, native models — moving would otherwise mark the report changed
and deliver a digest identical to the last one. Project-wide sections hash
once per project, the same way they render once per project.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any

from yoke_core.domain.steering_fleet_report_project_rows import ProjectRows

if TYPE_CHECKING:  # pragma: no cover - annotation only, no import cycle
    from yoke_core.domain.steering_fleet_report import FleetReport


def _holder_rows(holders: Any) -> list[tuple[Any, ...]]:
    return sorted(
        (
            holder.session_id,
            holder.item_id,
            holder.native_process_gone,
            holder.hand_started,
            holder.quiet_reason,
        )
        for holder in holders
    )


def seat_payload(report: "FleetReport") -> dict[str, Any]:
    """The age-blind material of the sections one seat renders itself."""
    return {
        "available": sorted(entry.item_id for entry in report.available),
        "idle": _holder_rows(report.idle),
        "suspected_orphaned_waiters": _holder_rows(report.suspected_orphaned_waiters),
        "vendor_errors": sorted(
            (entry.session_id, entry.status, entry.attempts)
            for entry in report.vendor_errors
        ),
        "stranded": sorted(
            (entry.session_id, entry.kind, entry.model) for entry in report.stranded
        ),
        "in_flight": sorted((c.session_id, c.command) for c in report.in_flight),
        "landings": sorted(
            (
                entry.item_id,
                entry.readiness.landing_state,
                entry.readiness.queue_entry_state,
                entry.readiness.merge_when_ready,
            )
            for entry in report.landings
        ),
        "dead_waits": sorted(
            (entry.session_id, entry.answerer_session_id, entry.reason)
            for entry in report.dead_waits
        ),
        "messages_awaiting_seat": report.messages_awaiting_seat,
    }


def project_payload(rows: ProjectRows) -> dict[str, Any]:
    """The age-blind material of one project's project-wide sections."""
    return {
        # Only settled deliveries count toward identity: an envelope the
        # plane is still inside its window for passes through this section
        # on every ordinary send, and hashing that would report the fleet as
        # changed for mail that is about to arrive by itself.
        "undelivered": sorted(
            (entry.session_id, entry.delivery_state)
            for entry in rows.undelivered
            if not entry.in_delivery
        ),
        "unregistered_launches": sorted(
            (entry.launch_id, entry.native_launch_phase, entry.spawn_duration_ms)
            for entry in rows.unregistered_launches
        ),
        "abandoned_launches": sorted(
            entry.launch_id for entry in rows.abandoned_launches
        ),
        # Custody joins identity because a landing moving from "a release is
        # delivering this" to "nothing holds it" is the finding this section
        # exists to raise, and a fingerprint blind to it would leave the seat
        # unwoken. The run id deliberately stays out: which release holds a
        # landing changes every batch and is not itself a finding.
        "landed_open": sorted(
            (entry.item_id, entry.custody_state) for entry in rows.visible_landed()
        ),
        "deployment_runs": sorted(
            (
                entry.run_id,
                entry.stage,
                entry.outstanding,
                entry.total_blocking,
                tuple(entry.unresolved),
                tuple(entry.no_obligation_lines),
                tuple(entry.member_lines),
                tuple(sorted(red.requirement_id for red in entry.red)),
                tuple(sorted(item.requirement_id for item in entry.pin_qa.unpassable)),
                tuple(sorted(item.requirement_id for item in entry.pin_qa.unproven)),
                (
                    (
                        entry.answered_decision.request_id,
                        entry.answered_decision.action,
                    )
                    if entry.answered_decision is not None
                    else None
                ),
            )
            for entry in rows.deployment_runs
        ),
    }


def fingerprint_payload(report: "FleetReport") -> dict[str, Any]:
    """The age-blind material one report rendered on its own hashes to."""
    return {**seat_payload(report), **project_payload(ProjectRows.of(report))}


def digest(material: Any) -> str:
    """Stable hex digest of JSON-encodable material."""
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def report_fingerprint(report: "FleetReport") -> str:
    """Stable hex digest of one report's content."""
    return digest(fingerprint_payload(report))


__all__ = [
    "digest",
    "fingerprint_payload",
    "project_payload",
    "report_fingerprint",
    "seat_payload",
]
