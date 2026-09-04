"""Content identity for one composed fleet report.

The fingerprint answers "is this the same report I already read", so it is
built from what the sections say and never from how old anything is: ages
advance on every pass, and a fingerprint that moved with them would mark
every report changed and teach the seat to ignore the signal entirely.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any

from yoke_core.domain.steering_fleet_report_limits import fingerprint_material

if TYPE_CHECKING:  # pragma: no cover - annotation only, no import cycle
    from yoke_core.domain.steering_fleet_report import FleetReport


def fingerprint_payload(report: "FleetReport") -> dict[str, Any]:
    """The age-blind material one report hashes to."""
    counts = {(machine, surface): n for machine, surface, n in report.session_counts}
    return {
        "available": sorted(entry.item_id for entry in report.available),
        "holders": sorted(
            (
                holder.session_id,
                holder.item_id,
                holder.native_process_gone,
                holder.hand_started,
            )
            for holder in report.holders
        ),
        "idle": sorted((holder.session_id, holder.item_id) for holder in report.idle),
        "starved": sorted(entry.session_id for entry in report.starved),
        "unregistered_launches": sorted(
            (entry.launch_id, entry.native_launch_phase, entry.spawn_duration_ms)
            for entry in report.unregistered_launches
        ),
        "abandoned_launches": sorted(
            entry.launch_id for entry in report.abandoned_launches
        ),
        "landed_open": sorted(entry.item_id for entry in report.landed_open),
        "suspected_orphaned_waiters": sorted(
            (holder.session_id, holder.item_id)
            for holder in report.suspected_orphaned_waiters
        ),
        "vendor_errors": sorted(
            (entry.session_id, entry.status, entry.attempts)
            for entry in report.vendor_errors
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
        "launch_balance": sorted(
            (r.machine_id, r.surface, counts.get((r.machine_id, r.surface), 0))
            for r in report.launchable
        ),
        "plan_limits": fingerprint_material(report.plan_limits),
        "machine_capacity": sorted(
            (c.machine_id, c.live_lanes, c.max_worker_lanes, c.at_capacity)
            for c in report.machine_capacity
        ),
        "origin_counts": list(report.origin_counts),
        "relay_health": sorted(
            (
                entry.relay_id,
                entry.state,
                entry.pending_reports,
                entry.quarantine_count,
                entry.error_code,
                entry.failure_count,
                entry.refusal_reason,
                entry.local_revision,
                entry.server_revision,
            )
            for entry in report.relay_health
        ),
        "messages_awaiting_seat": report.messages_awaiting_seat,
    }


def report_fingerprint(report: "FleetReport") -> str:
    """Stable hex digest of one report's content."""
    encoded = json.dumps(
        fingerprint_payload(report), sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


__all__ = ["fingerprint_payload", "report_fingerprint"]
