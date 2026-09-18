"""The line for envelopes a recipient has not read, and why.

Undelivered is where one visible symptom has several causes, and telling
them apart is the whole value of the line. A plane that never tried, one
whose every attempt refused for a nameable reason, one already escalated to
a wake, one whose wake the machine keeps holding because a native turn for
that session is already running, one only a person typing in a desktop chat
can feed, a recipient busy inside a tool call, and a recipient that is gone
all read as "nothing arrived" and want different responses from the seat --
or, for some of those groups, no response at all.

So the state decides the words. A waiting shape says it is waiting, and
never borrows the vocabulary of a failure; a gone recipient names the loss
and stops, because there is no route to suggest and nothing to revive.
"""

from __future__ import annotations

from yoke_contracts.session_control.evidence_fetch import evidence_pull_suffix
from yoke_core.domain.steering_fleet_report import FleetReport, UndeliveredMessages
from yoke_core.domain.steering_fleet_report_render_text import (
    SECTION_LIMIT,
    capped,
    minutes,
)
from yoke_core.domain.steering_fleet_report_delivery_states import (
    ATTEMPT_FAILED,
    ATTEMPT_IN_FLIGHT,
    AWAITING_ATTEMPT,
    NEVER_ATTEMPTED,
    RECIPIENT_ENDED,
    RECIPIENT_TERMINATED,
    TURN_IN_FLIGHT,
    WAKE_HELD_FOR_NATIVE_TURN,
)

#: What each state is, in the seat's terms. The two waiting shapes say so
#: outright: a queued delivery read as a failure sends the seat after work
#: that was about to happen on its own.
_STATE_PHRASES = {
    NEVER_ATTEMPTED: "never injected, no delivery attempted",
    ATTEMPT_IN_FLIGHT: "delivery attempt in flight — waiting",
    AWAITING_ATTEMPT: "queued for the recipient's next hook — waiting",
    RECIPIENT_ENDED: "recipient session ended",
    RECIPIENT_TERMINATED: "recipient session terminated",
}

#: States where naming a wake would be wrong: one has a hook already coming,
#: two have no recipient left to wake, and one already named the wake it is
#: holding, so appending "wake escalated" to it would read as progress.
_NO_WAKE_STATES = frozenset(
    {
        TURN_IN_FLIGHT,
        RECIPIENT_ENDED,
        RECIPIENT_TERMINATED,
        WAKE_HELD_FOR_NATIVE_TURN,
    }
)


def _references(entry: UndeliveredMessages) -> str:
    """Name the envelopes so the seat can read them, not just count them."""
    if not entry.message_ids:
        return ""
    shown = " ".join(entry.message_ids)
    remaining = entry.envelope_count - len(entry.message_ids)
    return f" [{shown}{f' +{remaining}' if remaining > 0 else ''}]"


def _state_phrase(entry: UndeliveredMessages) -> str:
    if entry.delivery_state == NEVER_ATTEMPTED and entry.queued_wake:
        # "No delivery attempted" is true and useless here: a wake WAS asked
        # for, the plane never picked it up, and that queued receipt is what
        # refuses the seat's next wake. Saying so is what makes the row
        # actionable rather than a restatement of the silence.
        return "never injected, wake queued but unattempted"
    if entry.delivery_state == TURN_IN_FLIGHT:
        return (
            f"recipient turn in flight since {entry.turn_in_flight_since} — "
            "waits for that call's hook, no resume"
        )
    if entry.delivery_state == ATTEMPT_FAILED:
        return f"never injected, last attempt failed ({entry.diagnostic})"
    if entry.delivery_state == WAKE_HELD_FOR_NATIVE_TURN:
        # Say what is holding it, whether that thing is moving, and what ends
        # the hold. The seat's only lever is the native itself, so the line
        # names it rather than suggesting another wake, which the machine
        # would hold for the same reason.
        return (
            "never injected, wake held — a native turn is already running "
            f"for this session{_held_silence(entry)}; it delivers when that "
            "turn ends, or end it with "
            f"`yoke sessions terminate {entry.session_id} --reason ...`"
        )
    phrase = _STATE_PHRASES[entry.delivery_state]
    if entry.recipient_gone_at:
        # The loss is the finding. No revive recipe follows: the envelope
        # stays addressed to the session it was sent to, and that session
        # is not coming back.
        return f"{phrase} {entry.recipient_gone_at} — no delivery route remains"
    return phrase


def _wake_suffix(entry: UndeliveredMessages) -> str:
    """Who owes the next move, for the states where anyone still does.

    An already-escalated recipient is a wake in flight rather than one the
    seat owes by hand, so the line says which absence authorized it. A
    desktop recipient is neither: Yoke never resumes one, so the line asks
    for the only thing that delivers it instead of naming a revive recipe.
    A queued-but-unattempted wake outranks the escalation note, because the
    escalation on that row describes the attempt that never happened.
    """
    if entry.delivery_state in _NO_WAKE_STATES:
        return ""
    if entry.queued_wake and not entry.operator_wake:
        # The recovery is the same command that was already asked for: it
        # releases the queued receipt that outlived its window and takes a
        # fresh route decision, so whatever refused the first attempt now
        # refuses by name instead of blocking silently.
        return (
            f", re-run `yoke session-control session wake {entry.session_id}` "
            "to release the queued wake and retry"
        )
    if entry.operator_wake:
        return (
            ", waiting for the operator to wake it — ask them to type "
            "anything in that chat"
        )
    if entry.wake_escalation:
        return f", wake escalated ({entry.wake_escalation})"
    return ""


def _held_silence(entry: UndeliveredMessages) -> str:
    """How long the holding native has said nothing, when that is known.

    A held wake reads the same whether the turn behind it is thinking or
    has stopped, and the seat's decision differs entirely between those.
    The native's own output clock separates them; an unknown silence says
    nothing rather than implying zero.
    """
    silent = entry.held_native_silent_for_seconds
    if silent is None:
        return ""
    return f" and silent for {minutes(silent)}"


def undelivered_line(entry: UndeliveredMessages) -> str:
    return (
        f"  session {entry.session_id}  {entry.envelope_count} message(s)"
        f"{_references(entry)}, oldest {minutes(entry.oldest_seconds)}, "
        f"{_state_phrase(entry)}{_wake_suffix(entry)}"
        f"{evidence_pull_suffix(entry.session_id, entry.evidence_id)}"
    )


def undelivered_lines(report: FleetReport) -> list[str]:
    lines = [undelivered_line(entry) for entry in report.undelivered[:SECTION_LIMIT]]
    return capped(lines, len(report.undelivered))


__all__ = ["undelivered_line", "undelivered_lines"]
