"""Envelopes nobody has read yet, each carrying why it has not landed.

Classify undelivered project receipts through steering_fleet_report_delivery_states
and group their reasons for the steering report.

Settled receipts are excluded; ended recipients include injected but
unacknowledged envelopes so unresolved work remains visible.

Grouping stays per recipient, split by state. The action is per recipient:
one session with four stuck envelopes is one worker to wake, not four
findings. Two states at once are two genuinely different situations, so they
get a line each rather than one line whose count and reason disagree.
"""

from __future__ import annotations

from yoke_core.domain.steering_fleet_report_detectors import parse_stamp

from yoke_core.domain.steering_fleet_report_message_groups import (
    MessageGroup,
    MESSAGE_REFERENCE_LIMIT,
)
from yoke_core.domain.db_helpers import instant_parameter
from yoke_core.domain.session_message_ended_recipient import (
    recipient_has_no_delivery_route,
)
from yoke_core.domain.session_message_visibility import visible_clause
from yoke_core.domain.session_tool_call_projections import open_tool_call_select

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from yoke_core.domain.session_message_authorization import project_policy
from yoke_core.domain.session_relay_policy import relay_policy
from yoke_core.domain.steering_fleet_report_attempt_summary import last_attempts
from yoke_core.domain.steering_fleet_report_queued_wake import (
    wake_release_times,
)
from yoke_core.domain.steering_fleet_report_delivery_states import (
    ATTEMPT_FAILED,
    WAKE_HELD_FOR_NATIVE_TURN,
    DELIVERY_STATES,
    IN_DELIVERY_STATES,
    SEAT_ACTION_STATES,
    delivery_state,
)


@dataclass(frozen=True)
class UndeliveredMessages:
    """One recipient's undelivered envelopes that share a delivery state."""

    session_id: str
    #: Which member of ``DELIVERY_STATES`` these envelopes are in.
    delivery_state: str
    envelope_count: int
    oldest_seconds: int
    #: Confirmed session item, retained after its work claim ends.
    item_id: int | None = None
    public_ref: str = ""
    item_project: str = ""
    #: Up to :data:`MESSAGE_REFERENCE_LIMIT` ids, oldest first, so the seat
    #: can read the envelope itself rather than infer it from the row.
    message_ids: tuple[str, ...] = ()
    #: Why the wake sweep already escalated, when it has; empty otherwise.
    wake_escalation: str = ""
    #: True when the recipient's surface is woken only by its own operator,
    #: so the finding is an ask to that person rather than work for the seat.
    operator_wake: bool = False
    #: How the last attempt failed, named. Empty unless the state is
    #: ``ATTEMPT_FAILED``. A repeating result includes its count.
    diagnostic: str = ""
    #: How many attempts on these envelopes already failed. Zero unless
    #: the state is ``ATTEMPT_FAILED``.
    failed_attempt_count: int = 0
    #: The diagnostic reference that attempt left on its own machine, so the
    #: row can name the exact capture rather than the session's newest file.
    evidence_id: str = ""
    #: When the recipient's still-running tool call started. Set only for
    #: ``TURN_IN_FLIGHT``, where it is the whole finding.
    turn_in_flight_since: datetime | None = None
    #: When the recipient ended or was terminated, for the two gone states.
    recipient_gone_at: datetime | None = None
    #: How long the native holding a declined wake has produced nothing, when
    #: its machine could measure that. Set only for the held state, where it
    #: is the difference between a turn that is working and one to look at.
    held_native_silent_for_seconds: int | None = None
    held_native_observed_at: datetime | None = None
    #: True when an explicit wake was requested for this recipient, the
    #: delivery plane has still made no attempt on it, and every such receipt
    #: has waited out the wake grace. The row then names a queued wake and
    #: the wake command that releases it, because the receipt itself is what
    #: refuses the next wake request until it is released.
    queued_wake: bool = False
    #: When the recipient's unattempted explicit wakes become releasable, set
    #: while one is still inside the wake grace. The wake command refuses a
    #: release before then, so the row names the moment instead of a recovery.
    wake_releasable_at: datetime | None = None

    @property
    def needs_seat_action(self) -> bool:
        """True when this delivery will not happen without the seat."""
        return self.delivery_state in SEAT_ACTION_STATES

    @property
    def in_delivery(self) -> bool:
        """True while the plane is still expected to deliver these itself."""
        return self.delivery_state in IN_DELIVERY_STATES


def report_receipts(
    conn: Any, *, project_id: int, now: Any, session_id: str | None = None
) -> list[dict[str, Any]]:
    """Keep normal deliveries and unresolved mail with no remaining recipient route.

    The report is read-only. Canonical expiry/cancellation and message visibility
    apply even before receipt-state sweeps converge.
    """
    from yoke_core.domain.steering_fleet_report_detectors import marker

    placeholder = marker(conn)
    visibility, visibility_params = "1=1", []
    if session_id is not None:
        caller = conn.execute(
            f"SELECT actor_id FROM harness_sessions WHERE session_id={placeholder}",
            (session_id,),
        ).fetchone()
        if caller is None or caller[0] is None:
            return []
        visibility, visibility_params = visible_clause(
            conn, actor_id=int(caller[0]), caller_session_id=session_id
        )
    open_call = open_tool_call_select(conn, session_alias="s")
    rows = conn.execute(
        f"""SELECT r.message_id AS message_id,
                   r.session_id AS session_id,
                   r.created_at AS created_at,
                   r.state AS receipt_state, r.injection_count AS injection_count,
                   i.id AS item_id, i.project_sequence AS project_sequence,
                   p.public_item_prefix AS item_prefix, p.slug AS item_project,
                   r.wake_escalation AS wake_escalation,
                   r.wake_attempt_count AS wake_attempt_count,
                   r.routing_snapshot AS routing_snapshot,
                   s.executor_surface AS executor_surface,
                   s.last_tool_call_at AS last_tool_call_at,
                   s.last_heartbeat AS last_heartbeat,
                   s.episode_started_at AS episode_started_at,
                   s.turn_posture AS turn_posture,
                   s.turn_posture_at AS turn_posture_at,
                   s.mode AS mode,
                   s.native_process_gone_at AS native_process_gone_at,
                   s.native_process_gone_evidence AS native_process_gone_evidence,
                   s.ended_at AS ended_at,
                   s.terminated_at AS terminated_at
                   {open_call}
              FROM session_message_recipients r
              JOIN session_messages m ON m.message_id = r.message_id
              JOIN harness_sessions s ON s.session_id = r.session_id
              LEFT JOIN items i ON CAST(i.id AS TEXT) =
                   COALESCE(NULLIF(s.current_item_id, ''), NULLIF(s.recent_item_id, ''))
                   AND i.project_id = r.project_id
              LEFT JOIN projects p ON p.id = i.project_id
             WHERE r.project_id = {placeholder}
               AND m.cancelled_at IS NULL AND m.expires_at > {placeholder}
               AND r.acknowledged_at IS NULL
               AND ((r.state = 'pending' AND COALESCE(r.injection_count, 0) = 0)
                    OR (r.state IN ('pending', 'injected')
                        AND (s.ended_at IS NOT NULL OR s.terminated_at IS NOT NULL)))
               AND {visibility}
             ORDER BY r.created_at, r.message_id""",
        (
            int(project_id),
            instant_parameter(conn, parse_stamp(now)),
            *visibility_params,
        ),
    ).fetchall()
    return [
        record
        for raw in rows
        if (record := dict(raw))["receipt_state"] == "pending"
        and not record.get("injection_count")
        or recipient_has_no_delivery_route(record)
    ]


def undelivered_messages(
    conn: Any,
    *,
    project_id: int,
    now: str,
    session_id: str | None = None,
) -> tuple[UndeliveredMessages, ...]:
    """Every undelivered envelope in one project, grouped by recipient and state.

    Sender is deliberately not a filter: a worker-to-worker envelope goes
    unread exactly like a steerer-sent one.
    """
    from yoke_core.domain.steering_fleet_report_detectors import (
        age_seconds,
        marker,
    )

    placeholder = marker(conn)
    # When the plane owes an attempt, and how long after that its absence is
    # the plane's failure rather than the next poll's ordinary work.
    grace = timedelta(
        seconds=int(project_policy(conn, int(project_id)).wake_ack_grace_seconds)
    )
    sla = timedelta(seconds=int(relay_policy().poll_seconds))
    attempts = last_attempts(conn, project_id=project_id, marker=placeholder, now=now)
    rows = report_receipts(conn, project_id=project_id, now=now, session_id=session_id)
    current = parse_stamp(now)
    records = [dict(raw) for raw in rows]
    wake_release_at = wake_release_times(records, grace=grace)
    groups: dict[tuple[str, str], MessageGroup] = {}
    for record in records:
        sent_at = parse_stamp(record.get("created_at"))
        waited = age_seconds(sent_at, now)
        if waited is None:
            continue
        session_id = str(record["session_id"])
        view = attempts.get((str(record["message_id"]), session_id))
        result_code = view.result_code if view else ""
        evidence = view.evidence if view else {}
        failed_count = view.failed_count if view else 0
        record.update(
            held_at=view.completed_at if view else None,
            wake_delivered_at=view.wake_delivered_at if view else None,
        )
        state = delivery_state(
            record,
            result_code=result_code,
            sent_at=sent_at,
            grace=grace,
            sla=sla,
            current=current,
            failed_count=failed_count,
            attempt_evidence=evidence,
        )
        group = groups.setdefault((session_id, state), MessageGroup())
        group.absorb(
            record,
            state=state,
            waited=waited,
            wake_release_at=wake_release_at.get(session_id),
            current=current,
        )
        group.failed_attempt_count = max(group.failed_attempt_count, failed_count)
        if state == ATTEMPT_FAILED:
            # An in-flight retry has no result of its own; name the last
            # refusal, but do not feed that code back into classification.
            if not result_code and view is not None and view.last_failed_code:
                result_code = view.last_failed_code
                evidence = view.last_failed_evidence
            group.name_the_failure(result_code=result_code, evidence=evidence)
        elif state == WAKE_HELD_FOR_NATIVE_TURN:
            group.note_held_native(
                evidence=evidence, observed_at=view.completed_at if view else None
            )
    return tuple(
        UndeliveredMessages(
            session_id=session_id,
            item_id=group.item_id,
            public_ref=group.public_ref,
            item_project=group.item_project,
            delivery_state=state,
            envelope_count=group.envelope_count,
            oldest_seconds=group.oldest_seconds,
            message_ids=tuple(group.message_ids),
            wake_escalation=group.wake_escalation,
            operator_wake=group.operator_wake,
            diagnostic=group.diagnostic,
            failed_attempt_count=group.failed_attempt_count,
            held_native_silent_for_seconds=group.held_native_silent_for_seconds,
            held_native_observed_at=group.held_native_observed_at,
            evidence_id=group.evidence_id,
            turn_in_flight_since=group.turn_in_flight_since,
            recipient_gone_at=group.recipient_gone_at,
            queued_wake=group.queued_wake,
            wake_releasable_at=group.wake_releasable_at,
        )
        for (session_id, state), group in sorted(
            groups.items(),
            key=lambda item: (
                DELIVERY_STATES.index(item[0][1]),
                -item[1].oldest_seconds,
                item[0][0],
            ),
        )
    )


__all__ = [
    "MESSAGE_REFERENCE_LIMIT",
    "UndeliveredMessages",
    "undelivered_messages",
]
