"""The machine-readable projection of one fleet report.

Same facts as the rendered text, shaped for a caller that queries rather
than reads: every section as a list of plain dicts, plus the fingerprint
and the actionable flag a poller keys on.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.steering_fleet_report import ClaimHolder, FleetReport
from yoke_core.domain.steering_fleet_report_available import FrontierEntry
from yoke_core.domain.steering_fleet_report_dead_waits import DeadWait
from yoke_core.domain.steering_fleet_report_starvation import (
    StarvedDelivery,
)
from yoke_core.domain.steering_fleet_report_detectors import (
    LandedItem,
    UnregisteredLaunch,
)
from yoke_core.domain import steering_fleet_plan_capacity as _plan_limits
from yoke_core.domain import steering_fleet_report_in_flight as _in_flight


def _landed_recovery(public_ref: str) -> str:
    return (
        f"finish close-out with `yoke merge item {public_ref}`; do not wait on status"
    )


def _entry_dict(entry: FrontierEntry, now: str) -> dict[str, Any]:
    return {
        "item_id": entry.item_id,
        "public_ref": entry.public_ref,
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
        "public_ref": holder.public_ref,
        "mode": holder.mode,
        "parked": holder.parked,
        "last_activity_at": holder.last_activity_at,
        "idle_seconds": holder.idle_seconds,
        "native_process_gone": holder.native_process_gone,
        "native_process_gone_at": holder.native_process_gone_at or None,
    }


def _starved_dict(entry: StarvedDelivery) -> dict[str, Any]:
    return {
        "session_id": entry.session_id,
        "envelope_count": entry.envelope_count,
        "oldest_seconds": entry.oldest_seconds,
        "wake_escalation": entry.wake_escalation,
        "operator_wake": entry.operator_wake,
        "attempt_count": entry.attempt_count,
        "diagnostic": entry.diagnostic,
    }


def _launch_dict(entry: UnregisteredLaunch) -> dict[str, Any]:
    return {
        "launch_id": entry.launch_id,
        "surface": entry.surface,
        "machine_id": entry.machine_id,
        "state": entry.state,
        "overdue_seconds": entry.overdue_seconds,
        "result_code": entry.result_code,
        "native_session_id": entry.native_session_id,
        "observed_session_id": entry.observed_session_id,
        "native_launch_pid": entry.native_launch_pid,
        "native_launch_phase": entry.native_launch_phase,
        "spawn_duration_ms": entry.spawn_duration_ms,
    }


def _landed_dict(entry: LandedItem) -> dict[str, Any]:
    return {
        "item_id": entry.item_id,
        "public_ref": entry.public_ref,
        "status": entry.status,
        "landed_at": entry.landed_at,
        "landed_seconds": entry.landed_seconds,
        "recovery": _landed_recovery(entry.public_ref),
    }


def _dead_wait_dict(entry: DeadWait) -> dict[str, Any]:
    return {
        "session_id": entry.session_id,
        "item_id": entry.item_id,
        "public_ref": entry.public_ref,
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
        "suspected_orphaned_waiters": [
            _holder_dict(holder) for holder in report.suspected_orphaned_waiters
        ],
        "in_flight": _in_flight.in_flight_dicts(report.in_flight),
        "dead_waits": [_dead_wait_dict(entry) for entry in report.dead_waits],
        "launchable": [
            {"machine_id": ready.machine_id, "surface": ready.surface}
            for ready in report.launchable
        ],
        "plan_limits": _plan_limits.plan_limit_dicts(
            report.plan_limits, now=report.composed_at
        ),
        "origin_counts": list(report.origin_counts),
        "messages_awaiting_seat": report.messages_awaiting_seat,
    }


__all__ = ["report_dict"]
