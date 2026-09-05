"""Envelopes nobody has read yet, each carrying why it has not landed.

A steering seat reads this section to find a worker still waiting on a
message. What it needs is not that nothing arrived -- it is which of several
unrelated reasons nothing arrived, and that vocabulary lives in
:mod:`steering_fleet_report_delivery_states`. This module asks the database
for every undelivered receipt in a project, classifies each one, and folds
them into the rows the report renders.

Two decisions shape the query. Terminal receipts are never included, on the
delivery plane's own test rather than the receipt's ``state`` column, so an
envelope past its expiry but ahead of the sweep does not read as a worker
left waiting. Recipients that have ended or been terminated ARE included and
labelled as such: an envelope addressed to a session that is gone is the one
shape no later poll will ever resolve, and dropping it made the loss
invisible to the only reader who could act on it.

Grouping stays per recipient, split by state. The action is per recipient:
one session with four stuck envelopes is one worker to wake, not four
findings. Two states at once are two genuinely different situations, so they
get a line each rather than one line whose count and reason disagree.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Mapping

from yoke_contracts.session_control.capabilities import native_wake_supported
from yoke_contracts.session_control.evidence import (
    valid_native_diagnostic_reference,
)
from yoke_contracts.session_control.wake_delivery import (
    delivery_attempt_diagnostic,
)
from yoke_core.domain import json_helper
from yoke_core.domain.session_activity_state import (
    OPEN_TOOL_CALL_COLUMN,
    open_tool_call_select,
)
from yoke_core.domain.session_message_authorization import project_policy
from yoke_core.domain.session_relay_policy import effective_relay_policy
from yoke_core.domain.steering_fleet_report_delivery_states import (
    ATTEMPT_FAILED,
    DELIVERY_STATES,
    IN_DELIVERY_STATES,
    RECIPIENT_ENDED,
    RECIPIENT_TERMINATED,
    SEAT_ACTION_STATES,
    TURN_IN_FLIGHT,
    deliverable_receipt,
    delivery_state,
)

#: How many message ids one row prints. Enough for the seat to look the
#: envelopes up, bounded so a recipient with a hundred cannot flood the row;
#: the count carries the rest.
MESSAGE_REFERENCE_LIMIT = 3


@dataclass(frozen=True)
class UndeliveredMessages:
    """One recipient's undelivered envelopes that share a delivery state."""

    session_id: str
    #: Which member of ``DELIVERY_STATES`` these envelopes are in.
    delivery_state: str
    envelope_count: int
    oldest_seconds: int
    #: Up to :data:`MESSAGE_REFERENCE_LIMIT` ids, oldest first, so the seat
    #: can read the envelope itself rather than infer it from the row.
    message_ids: tuple[str, ...] = ()
    #: Why the wake sweep already escalated, when it has; empty otherwise.
    wake_escalation: str = ""
    #: True when the recipient's surface is woken only by its own operator,
    #: so the finding is an ask to that person rather than work for the seat.
    operator_wake: bool = False
    #: How the last attempt failed, named. Empty unless the state is
    #: ``ATTEMPT_FAILED``.
    diagnostic: str = ""
    #: The diagnostic reference that attempt left on its own machine, so the
    #: row can name the exact capture rather than the session's newest file.
    evidence_id: str = ""
    #: When the recipient's still-running tool call started. Set only for
    #: ``TURN_IN_FLIGHT``, where it is the whole finding.
    turn_in_flight_since: str = ""
    #: When the recipient ended or was terminated, for the two gone states.
    recipient_gone_at: str = ""

    @property
    def needs_seat_action(self) -> bool:
        """True when this delivery will not happen without the seat."""
        return self.delivery_state in SEAT_ACTION_STATES

    @property
    def in_delivery(self) -> bool:
        """True while the plane is still expected to deliver these itself."""
        return self.delivery_state in IN_DELIVERY_STATES


def _last_attempts(
    conn: Any, *, project_id: int, marker: str, now: str
) -> dict[tuple[str, str], tuple[str, Mapping[str, Any]]]:
    """Return each undelivered receipt's most recent attempt, keyed by receipt."""
    rows = conn.execute(
        f"""SELECT a.message_id AS message_id,
                   a.target_session_id AS target_session_id,
                   a.result_code AS result_code,
                   a.evidence AS evidence
              FROM session_message_attempts a
              JOIN session_message_recipients r
                ON r.message_id = a.message_id
               AND r.session_id = a.target_session_id
              JOIN session_messages m ON m.message_id = r.message_id
             WHERE {deliverable_receipt(marker)}
             ORDER BY a.started_at, a.attempt_id""",
        (int(project_id), now),
    ).fetchall()
    latest: dict[tuple[str, str], tuple[str, Mapping[str, Any]]] = {}
    for raw in rows:
        row = dict(raw)
        evidence = row.get("evidence")
        if isinstance(evidence, str):
            try:
                evidence = json_helper.loads_text(evidence)
            except (TypeError, ValueError):
                evidence = {}
        latest[(str(row["message_id"]), str(row["target_session_id"]))] = (
            str(row.get("result_code") or ""),
            evidence if isinstance(evidence, Mapping) else {},
        )
    return latest


@dataclass
class _Group:
    """Mutable accumulator for one (recipient, state) row."""

    oldest_seconds: int = 0
    envelope_count: int = 0
    message_ids: list[str] = None  # type: ignore[assignment]
    wake_escalation: str = ""
    operator_wake: bool = False
    diagnostic: str = ""
    evidence_id: str = ""
    turn_in_flight_since: str = ""
    recipient_gone_at: str = ""

    def __post_init__(self) -> None:
        if self.message_ids is None:
            self.message_ids = []

    def absorb(self, record: Mapping[str, Any], *, state: str, waited: int) -> None:
        """Fold one receipt's facts into this row."""
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
            self.turn_in_flight_since = str(record.get(OPEN_TOOL_CALL_COLUMN) or "")
        if state in (RECIPIENT_ENDED, RECIPIENT_TERMINATED):
            self.recipient_gone_at = str(
                record.get("terminated_at") or record.get("ended_at") or ""
            )
        # A desktop recipient is never resumed by Yoke, so this row is not
        # a worker to revive; it names a chat only its operator can open.
        if not native_wake_supported(str(record.get("executor_surface") or "")):
            self.operator_wake = True

    def name_the_failure(
        self, *, result_code: str, evidence: Mapping[str, Any]
    ) -> None:
        """Record how the attempt failed and where its capture lives."""
        self.diagnostic = (
            delivery_attempt_diagnostic(result_code, evidence) or self.diagnostic
        )
        reference = valid_native_diagnostic_reference(
            evidence.get("native_diagnostic_ref")
        )
        if reference is not None:
            self.evidence_id = reference


def undelivered_messages(
    conn: Any,
    *,
    project_id: int,
    now: str,
) -> tuple[UndeliveredMessages, ...]:
    """Every undelivered envelope in one project, grouped by recipient and state.

    Sender is deliberately not a filter: a worker-to-worker envelope goes
    unread exactly like a steerer-sent one.
    """
    from yoke_core.domain.steering_fleet_report_detectors import (
        age_seconds,
        marker,
        parse_stamp,
    )

    placeholder = marker(conn)
    # When the plane owes an attempt, and how long after that its absence is
    # the plane's failure rather than the next poll's ordinary work.
    grace = timedelta(
        seconds=int(project_policy(conn, int(project_id)).wake_ack_grace_seconds)
    )
    sla = timedelta(
        seconds=int(effective_relay_policy(conn, [int(project_id)]).poll_seconds)
    )
    attempts = _last_attempts(
        conn, project_id=project_id, marker=placeholder, now=now
    )
    open_call = open_tool_call_select(conn, session_alias="s")
    rows = conn.execute(
        f"""SELECT r.message_id AS message_id,
                   r.session_id AS session_id,
                   r.created_at AS created_at,
                   r.wake_escalation AS wake_escalation,
                   s.executor_surface AS executor_surface,
                   s.last_tool_call_at AS last_tool_call_at,
                   s.ended_at AS ended_at,
                   s.terminated_at AS terminated_at
                   {open_call}
              FROM session_message_recipients r
              JOIN session_messages m ON m.message_id = r.message_id
              JOIN harness_sessions s ON s.session_id = r.session_id
             WHERE {deliverable_receipt(placeholder)}
             ORDER BY r.created_at, r.message_id""",
        (int(project_id), now),
    ).fetchall()
    current = parse_stamp(now)
    groups: dict[tuple[str, str], _Group] = {}
    for raw in rows:
        record = dict(raw)
        sent_at = str(record.get("created_at") or "")
        waited = age_seconds(sent_at, now)
        if waited is None:
            continue
        session_id = str(record["session_id"])
        result_code, evidence = attempts.get(
            (str(record["message_id"]), session_id), ("", {})
        )
        state = delivery_state(
            record,
            result_code=result_code,
            sent_at=sent_at,
            grace=grace,
            sla=sla,
            current=current,
        )
        group = groups.setdefault((session_id, state), _Group())
        group.absorb(record, state=state, waited=waited)
        if state == ATTEMPT_FAILED:
            group.name_the_failure(result_code=result_code, evidence=evidence)
    return tuple(
        UndeliveredMessages(
            session_id=session_id,
            delivery_state=state,
            envelope_count=group.envelope_count,
            oldest_seconds=group.oldest_seconds,
            message_ids=tuple(group.message_ids),
            wake_escalation=group.wake_escalation,
            operator_wake=group.operator_wake,
            diagnostic=group.diagnostic,
            evidence_id=group.evidence_id,
            turn_in_flight_since=group.turn_in_flight_since,
            recipient_gone_at=group.recipient_gone_at,
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
