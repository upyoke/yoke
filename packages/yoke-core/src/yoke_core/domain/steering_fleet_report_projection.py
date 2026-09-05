"""The machine-readable projection of one fleet report.

Same facts as the rendered text, shaped for a caller that queries rather
than reads: every section as a list of plain dicts, plus the fingerprint
and the actionable flag a poller keys on.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.steering_fleet_report import ClaimHolder, FleetReport
from yoke_core.domain.steering_fleet_report_balance import session_selection_label
from yoke_core.domain.steering_fleet_report_available import FrontierEntry
from yoke_core.domain.steering_fleet_report_dead_waits import DeadWait
from yoke_core.domain.steering_fleet_report_undelivered import (
    UndeliveredMessages,
)
from yoke_core.domain.steering_fleet_report_detectors import (
    LandedItem,
    UnregisteredLaunch,
    landed_recovery,
)
from yoke_core.domain.steering_fleet_report_vendor_errors import VendorErrorSession
from yoke_core.domain import steering_fleet_plan_capacity as _plan_limits
from yoke_core.domain import steering_fleet_report_in_flight as _in_flight


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
        "quiet_reason": holder.quiet_reason or None,
        "native_process_gone": holder.native_process_gone,
        "native_process_gone_at": holder.native_process_gone_at or None,
        "hand_started": holder.hand_started,
    }


def _undelivered_dict(entry: UndeliveredMessages) -> dict[str, Any]:
    return {
        "session_id": entry.session_id,
        "delivery_state": entry.delivery_state,
        "needs_seat_action": entry.needs_seat_action,
        "envelope_count": entry.envelope_count,
        "oldest_seconds": entry.oldest_seconds,
        "message_ids": list(entry.message_ids),
        "wake_escalation": entry.wake_escalation,
        "operator_wake": entry.operator_wake,
        "diagnostic": entry.diagnostic,
        "evidence_id": entry.evidence_id,
        "turn_in_flight_since": entry.turn_in_flight_since,
        "recipient_gone_at": entry.recipient_gone_at,
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
        "evidence_id": entry.evidence_id,
        "native_launch_pid": entry.native_launch_pid,
        "native_launch_phase": entry.native_launch_phase,
        "native_stderr_tail": entry.native_stderr_tail,
        "exit_code": entry.exit_code,
        "spawn_duration_ms": entry.spawn_duration_ms,
        "detail": entry.detail,
    }


def _landed_dict(entry: LandedItem) -> dict[str, Any]:
    return {
        "item_id": entry.item_id,
        "public_ref": entry.public_ref,
        "status": entry.status,
        "landed_at": entry.landed_at,
        "landed_seconds": entry.landed_seconds,
        "holder_session_id": entry.holder_session_id,
        "recovery": landed_recovery(entry.public_ref),
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


def _vendor_error_dict(entry: VendorErrorSession) -> dict[str, Any]:
    return {
        "session_id": entry.session_id,
        "item_id": entry.item_id,
        "public_ref": entry.public_ref,
        "signature_id": entry.signature_id,
        "error_message": entry.error_message,
        "observed_at": entry.observed_at,
        "stopped_seconds": entry.stopped_seconds,
        "status": entry.status,
        "reason": entry.reason,
        "due_at": entry.due_at,
        "attempts": entry.attempts,
        "budget": entry.budget,
        "executor_surface": entry.executor_surface,
        "executor_version": entry.executor_version,
        "seat_owed": entry.seat_owed,
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
        "undelivered": [_undelivered_dict(entry) for entry in report.undelivered],
        "undelivered_needing_action": [
            _undelivered_dict(entry) for entry in report.undelivered_needing_action()
        ],
        "unregistered_launches": [
            _launch_dict(entry) for entry in report.unregistered_launches
        ],
        "abandoned_launches": [
            {
                "launch_id": entry.launch_id,
                "surface": entry.surface,
                "machine_id": entry.machine_id,
                "session_id": entry.session_id,
                "closed_seconds": entry.closed_seconds,
                "closure_reason": entry.closure_reason,
                "native_stderr_tail": entry.native_stderr_tail,
                "native_diagnostic_ref": entry.native_diagnostic_ref,
                "exit_code": entry.exit_code,
            }
            for entry in report.abandoned_launches
        ],
        "landed_open": [_landed_dict(entry) for entry in report.landed_open],
        "suspected_orphaned_waiters": [
            _holder_dict(holder) for holder in report.suspected_orphaned_waiters
        ],
        "in_flight": _in_flight.in_flight_dicts(report.in_flight),
        "landings": [entry.to_dict() for entry in report.landings],
        "landings_needing_action": [
            entry.to_dict() for entry in report.landings_needing_action()
        ],
        "dead_waits": [_dead_wait_dict(entry) for entry in report.dead_waits],
        "vendor_errors": [_vendor_error_dict(entry) for entry in report.vendor_errors],
        "launchable": [
            {"machine_id": ready.machine_id, "surface": ready.surface}
            for ready in report.launchable
        ],
        "session_counts": [
            {
                **row.__dict__,
                "selection_display": session_selection_label(row),
            }
            for row in report.session_counts
        ],
        "plan_limits": _plan_limits.plan_limit_dicts(
            report.plan_limits,
            now=report.composed_at,
            session_counts=report.session_counts,
        ),
        "machine_capacity": [entry.to_dict() for entry in report.machine_capacity],
        "origin_counts": list(report.origin_counts),
        "relay_health": [
            {
                "relay_id": entry.relay_id,
                "machine_id": entry.machine_id,
                "hostname": entry.hostname,
                "state": entry.state,
                "pending_reports": entry.pending_reports,
                "quarantine_count": entry.quarantine_count,
                "error_code": entry.error_code,
                "failure_count": entry.failure_count,
                "first_failed_at": entry.first_failed_at,
                "last_failed_at": entry.last_failed_at,
                "refusal_reason": entry.refusal_reason,
                "local_revision": entry.local_revision,
                "server_revision": entry.server_revision,
                "recovery": entry.recovery,
            }
            for entry in report.relay_health
        ],
        "messages_awaiting_seat": report.messages_awaiting_seat,
    }


__all__ = ["report_dict"]
