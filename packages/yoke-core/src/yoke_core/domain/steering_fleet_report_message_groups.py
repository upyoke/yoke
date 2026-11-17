"""Accumulate delivery facts for one recipient and delivery state."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

from yoke_contracts.session_control.capabilities import native_wake_supported
from yoke_contracts.session_control.evidence import valid_native_diagnostic_reference
from yoke_contracts.session_control.wake_delivery import delivery_attempt_diagnostic
from yoke_core.domain.session_tool_call_projections import OPEN_TOOL_CALL_COLUMN
from yoke_core.domain.steering_fleet_report_detectors import parse_stamp
from yoke_core.domain.steering_fleet_report_queued_wake import unattempted_explicit_wake
from yoke_core.domain.steering_fleet_report_delivery_states import (
    NEVER_ATTEMPTED,
    WAKE_DRAINING,
    RECIPIENT_ENDED,
    RECIPIENT_TERMINATED,
    TURN_IN_FLIGHT,
)

MESSAGE_REFERENCE_LIMIT = 3


@dataclass
class MessageGroup:
    """Mutable accumulator for one (recipient, state) row."""

    item_id: int | None = None
    public_ref: str = ""
    item_project: str = ""
    oldest_seconds: int = 0
    envelope_count: int = 0
    message_ids: list[str] = None  # type: ignore[assignment]
    wake_escalation: str = ""
    operator_wake: bool = False
    diagnostic: str = ""
    evidence_id: str = ""
    turn_in_flight_since: datetime | None = None
    recipient_gone_at: datetime | None = None
    held_native_silent_for_seconds: int | None = None
    held_native_observed_at: datetime | None = None
    held_turn_ended_at: datetime | None = None
    held_background_child: tuple[int, str] | None = None
    held_background_count: int = 0
    wake_queue_positions: list[tuple[str, int]] = field(default_factory=list)
    queued_wake: bool = False
    wake_releasable_at: datetime | None = None
    failed_attempt_count: int = 0

    def __post_init__(self) -> None:
        if self.message_ids is None:
            self.message_ids = []

    def absorb(
        self,
        record: Mapping[str, Any],
        *,
        state: str,
        waited: int,
        wake_release_at: datetime | None,
        current: datetime,
    ) -> None:
        """Fold one receipt's facts into this row."""
        self.item_id = record.get("item_id")
        if self.item_id is not None:
            self.public_ref = f"{record['item_prefix']}-{record['project_sequence']}"
            self.item_project = str(record["item_project"])
        if state == WAKE_DRAINING:
            self.wake_queue_positions.append(
                (str(record["message_id"]), int(record["wake_queue_position"]))
            )
        self.envelope_count += 1
        self.oldest_seconds = max(self.oldest_seconds, waited)
        if len(self.message_ids) < MESSAGE_REFERENCE_LIMIT:
            self.message_ids.append(str(record["message_id"]))
        # A recipient the sweep already escalated needs no hand resume, so
        # the finding says which absence authorized that wake rather than
        # reading like an envelope nothing has acted on.
        escalation = str(record.get("wake_escalation") or "")
        if escalation:
            self.wake_escalation = escalation
        if state == TURN_IN_FLIGHT:
            self.turn_in_flight_since = parse_stamp(record.get(OPEN_TOOL_CALL_COLUMN))
        # An explicit wake still at zero attempts is not a missing wake, it
        # is a wake the plane never picked up — and that receipt blocks the
        # next wake request for this session until something releases it.
        # The wake command releases it only once it has waited out the grace.
        if (
            state == NEVER_ATTEMPTED
            and unattempted_explicit_wake(record)
            and wake_release_at is not None
        ):
            if wake_release_at <= current:
                self.queued_wake = True
            else:
                self.wake_releasable_at = wake_release_at
        if state in (RECIPIENT_ENDED, RECIPIENT_TERMINATED):
            self.recipient_gone_at = parse_stamp(
                record.get("terminated_at")
                if record.get("terminated_at") is not None
                else record.get("ended_at")
            )
        # A desktop recipient is never resumed by Yoke, so this row is not
        # a worker to revive; it names a chat only its operator can open.
        if not native_wake_supported(
            str(record.get("executor_surface") or ""), record.get("launch_origin")
        ):
            self.operator_wake = True

    def name_the_failure(
        self, *, result_code: str, evidence: Mapping[str, Any]
    ) -> None:
        """Record how the attempt failed and where its capture lives."""
        reason = delivery_attempt_diagnostic(result_code, evidence) or self.diagnostic
        if self.failed_attempt_count > 1 and reason:
            reason = f"{reason} ×{self.failed_attempt_count}"
        self.diagnostic = reason
        reference = valid_native_diagnostic_reference(
            evidence.get("native_diagnostic_ref")
        )
        if reference is not None:
            self.evidence_id = reference

    def note_held_native(
        self,
        record: Mapping[str, Any],
        *,
        evidence: Mapping[str, Any],
        observed_at: datetime | None,
        current: datetime,
    ) -> None:
        """Name what holds the native: a running turn, or an ended one's children.

        A Stop posture newer than every recorded tool call means the turn
        ended and the process outlived it, which only a background command
        does. The machine names those commands; the posture says they are
        the hold rather than the current tool call.
        """
        latest_tool_call_at = parse_stamp(record.get("latest_tool_call_started_at"))
        acted_at = _latest(
            latest_tool_call_at, parse_stamp(record.get("last_tool_call_at"))
        )
        posture_at = parse_stamp(record.get("turn_posture_at"))
        if (
            record.get("turn_posture") == "waiting"
            and posture_at is not None
            and (acted_at is None or posture_at > acted_at)
        ):
            self.held_turn_ended_at = posture_at
            self.held_background_child, self.held_background_count = (
                _background_child(evidence)
            )
        silent = evidence.get("running_native_silent_for_seconds")
        if isinstance(silent, int) and not isinstance(silent, bool):
            if latest_tool_call_at is not None:
                tool_silence = max(
                    0, int((current - latest_tool_call_at).total_seconds())
                )
                if tool_silence < silent:
                    silent, observed_at = tool_silence, current
            self.held_native_silent_for_seconds = silent
            self.held_native_observed_at = observed_at


def _latest(*stamps: datetime | None) -> datetime | None:
    present = [stamp for stamp in stamps if stamp is not None]
    return max(present) if present else None


def _background_child(
    evidence: Mapping[str, Any],
) -> tuple[tuple[int, str] | None, int]:
    """The first command the machine named, and how many it found.

    A relay that predates these fields sends neither, which reads as no
    command named rather than as no command running.
    """
    pid = evidence.get("running_native_background_pid")
    if not isinstance(pid, int) or isinstance(pid, bool):
        return None, 0
    count = evidence.get("running_native_background_count")
    command = str(evidence.get("running_native_background_command") or "")
    return (pid, command), count if isinstance(count, int) and count > 0 else 1
