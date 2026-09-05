"""Which of seven reasons an envelope has not been read yet.

A message that has not landed is one symptom with unrelated causes, and the
responses to them are opposite. A plane that never tried needs a wake. An
attempt that refused for a nameable reason needs that reason fixed. An
attempt already in flight needs nothing but a moment. A recipient inside a
tool call needs to be left alone, because the envelope lands on that call's
own hook and a resume would start a second turn on the same conversation.
A recipient that no longer exists cannot be given the message at all.

So classification is a closed vocabulary rather than a pair of booleans, and
every reader downstream -- the row, its rendered line, the alarm count, the
report's content identity -- keys on the same member. Labelling one shape
with another's words is the defect this module exists to prevent: reporting
a waiting delivery as a failure sends the seat after something that was
about to happen, and reporting a failure as waiting hides the finding.

:func:`deliverable_receipt` belongs here for the same reason. It is the
delivery plane's own test for a receipt still worth delivering, and sharing
it is what keeps a finished envelope out of the undelivered view: expiry and
cancellation converge on a sweep, so between the deadline and the sweep the
row still reads ``pending`` while nothing will ever deliver it.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Mapping

from yoke_contracts.session_control.wake_delivery import delivery_attempt_failed
from yoke_core.domain.session_activity_state import OPEN_TOOL_CALL_COLUMN
from yoke_core.domain.session_message_starvation import hook_route_silent_since

#: An attempt was made and settled badly. It names its own reason.
ATTEMPT_FAILED = "attempt_failed"
#: The plane owed an attempt, its window passed, and it made none.
NEVER_ATTEMPTED = "never_attempted"
#: An attempt is accepted and has not settled either way yet.
ATTEMPT_IN_FLIGHT = "attempt_in_flight"
#: No attempt yet and none owed: the recipient's next hook attaches it.
AWAITING_ATTEMPT = "awaiting_attempt"
#: The recipient is inside a tool call that has not returned. No hook runs
#: until it does, so the envelope lands on that call's own hook.
TURN_IN_FLIGHT = "turn_in_flight"
#: The recipient wound down. The envelope has no route left.
RECIPIENT_ENDED = "recipient_ended"
#: The recipient was terminated. Same absence, deliberately caused.
RECIPIENT_TERMINATED = "recipient_terminated"

#: The states that are a delivery the seat has to do something about. Every
#: other state is either still progressing or beyond anyone's reach, and
#: counting those as findings raises the alarm for ordinary fleet traffic.
SEAT_ACTION_STATES = frozenset({ATTEMPT_FAILED, NEVER_ATTEMPTED})

#: The states where the plane is still inside its own delivery window, so
#: the envelope is expected to arrive without anyone doing anything. These
#: are reported and deliberately left out of the report's content identity:
#: every ordinary send passes through one of them, and letting that churn
#: the fingerprint would turn routine fleet traffic into changed-report
#: wakes for mail that is about to land on its own.
IN_DELIVERY_STATES = frozenset({ATTEMPT_IN_FLIGHT, AWAITING_ATTEMPT})

#: Worst first, so a capped section drops waiting noise and not real
#: findings: what the seat owes, then what it can only be told, then what
#: is still on its way.
DELIVERY_STATES = (
    ATTEMPT_FAILED,
    NEVER_ATTEMPTED,
    RECIPIENT_TERMINATED,
    RECIPIENT_ENDED,
    ATTEMPT_IN_FLIGHT,
    TURN_IN_FLIGHT,
    AWAITING_ATTEMPT,
)


def deliverable_receipt(marker: str) -> str:
    """The delivery plane's own test for a receipt still worth delivering.

    Every clause matches what :mod:`session_message_delivery` requires
    before it will lease a receipt for injection, so a receipt the plane
    would refuse is finished whatever its row still says.

    Binds ``project_id`` then the current timestamp.
    """
    return (
        "r.state = 'pending' "
        "AND COALESCE(r.injection_count, 0) = 0 "
        f"AND r.project_id = {marker} "
        f"AND m.cancelled_at IS NULL AND m.expires_at > {marker}"
    )


def _attempt_owed(
    record: Mapping[str, Any],
    *,
    sent_at: str,
    grace: timedelta,
    sla: timedelta,
    current: Any,
) -> bool:
    """True when the plane should already have attempted this receipt.

    The clock is the recipient's own silence rather than the envelope's age,
    so silence that accrued before the message counts: a worker quiet for
    four hours will not run the hook that would attach an envelope sent two
    minutes ago. One relay poll after that moment the attempt should exist.
    """
    from yoke_core.domain.steering_fleet_report_detectors import parse_stamp

    acted = str(record.get("last_tool_call_at") or "")
    if acted and parse_stamp(acted) >= parse_stamp(sent_at):
        # A hook has run since the send, so the next one attaches this.
        return False
    silent_since = hook_route_silent_since(
        {"last_tool_call_at": acted or None, "message_created_at": sent_at}
    )
    if silent_since is None:
        return False
    owed_at = max(silent_since + grace, parse_stamp(sent_at))
    return owed_at + sla <= current


def delivery_state(
    record: Mapping[str, Any],
    *,
    result_code: str,
    sent_at: str,
    grace: timedelta,
    sla: timedelta,
    current: Any,
) -> str:
    """Classify one undelivered receipt into exactly one delivery state.

    A gone recipient is decided first because nothing later can change it,
    and an open tool call next because a hook is already coming: both
    override an earlier failed attempt, which describes a route the
    recipient's own turn has since overtaken.
    """
    if str(record.get("terminated_at") or ""):
        return RECIPIENT_TERMINATED
    if str(record.get("ended_at") or ""):
        return RECIPIENT_ENDED
    if str(record.get(OPEN_TOOL_CALL_COLUMN) or ""):
        return TURN_IN_FLIGHT
    if result_code:
        if delivery_attempt_failed(result_code):
            return ATTEMPT_FAILED
        return ATTEMPT_IN_FLIGHT
    if _attempt_owed(
        record, sent_at=sent_at, grace=grace, sla=sla, current=current
    ):
        return NEVER_ATTEMPTED
    return AWAITING_ATTEMPT


__all__ = [
    "ATTEMPT_FAILED",
    "ATTEMPT_IN_FLIGHT",
    "AWAITING_ATTEMPT",
    "DELIVERY_STATES",
    "IN_DELIVERY_STATES",
    "NEVER_ATTEMPTED",
    "RECIPIENT_ENDED",
    "RECIPIENT_TERMINATED",
    "SEAT_ACTION_STATES",
    "TURN_IN_FLIGHT",
    "delivery_state",
    "deliverable_receipt",
]
