"""Whether a native wake actually handed its envelope to the session.

A relay can only report what it saw of the native it started: the resume was
accepted, the resume process is still running, the resume process exited.
None of those is the thing a wake exists to accomplish. Delivery happens
*inside* the resumed turn, when a hook attaches the pending envelope, and a
turn that answers in prose and ends runs no hook at all — so a resume can be
accepted, complete cleanly, and deliver nothing.

Recording that transport observation in the field readers treat as the
outcome is what let three consecutive accepted wakes sit against a receipt
with zero injections while the plane reported each one a success. So the
reported code is held as unverified, the control plane settles the attempt
from the receipt's own injection facts, and the two verdicts below are the
only terminal answers a wake attempt reaches: delivered, or resumed without
delivering.
"""

from __future__ import annotations

from yoke_contracts.session_control.resume import (
    RESUME_RELAY_SETTLEMENT_RESULTS,
    RESUME_RESULT_CODES,
    RESUMED_COMPLETED_RESULT,
    RESUMED_RUNNING_RESULT,
    resume_roster_state,
)


#: What a relay reports when the native took the resume. It says nothing
#: about delivery, which is why it is unverified rather than terminal.
NATIVE_RESUME_ACCEPTED_RESULT = "accepted"

#: The envelope reached the session: the receipt records an injection, or an
#: acknowledgement, after this attempt started.
WAKE_DELIVERED_RESULT = "wake_delivered"

#: The resume ran and the envelope never arrived. Named rather than silent,
#: because an accepted attempt that delivered nothing is the failure this
#: whole verdict exists to stop reporting as a success.
TURN_WITHOUT_INJECTION_RESULT = "turn_without_injection"

#: Reported codes that leave delivery unproven. An attempt carrying one of
#: these stays open until the control plane settles it.
WAKE_DELIVERY_UNVERIFIED_RESULTS = frozenset(
    {
        NATIVE_RESUME_ACCEPTED_RESULT,
        RESUMED_RUNNING_RESULT,
        RESUMED_COMPLETED_RESULT,
    }
)

WAKE_DELIVERY_VERDICTS = frozenset(
    {WAKE_DELIVERED_RESULT, TURN_WITHOUT_INJECTION_RESULT}
)

#: Every result a relay may report for a wake job. The delivery verdicts are
#: deliberately absent: whether the envelope arrived is the control plane's to
#: observe from the receipt, never a relay's to claim.
WAKE_REPORT_CODES = frozenset(
    "failed not_found outcome_unknown thread_id_unknown "
    "unsupported_surface version_mismatch".split()
    + [
        NATIVE_RESUME_ACCEPTED_RESULT,
        RESUMED_RUNNING_RESULT,
        *RESUME_RELAY_SETTLEMENT_RESULTS,
    ]
)

#: Results that are, or may still become, a wake that delivered. Everything
#: else a wake attempt can carry is a failure.
WAKE_ATTEMPT_SUCCESS_RESULTS = frozenset(
    {WAKE_DELIVERED_RESULT, *WAKE_DELIVERY_UNVERIFIED_RESULTS}
)


def wake_attempt_unsettled(result_code: object) -> bool:
    """True while this attempt's delivery verdict has not landed yet."""
    return result_code in WAKE_DELIVERY_UNVERIFIED_RESULTS


#: Every result a wake attempt can carry that the session roster reports on.
WAKE_ATTEMPT_ROSTER_RESULTS = frozenset({*RESUME_RESULT_CODES, *WAKE_DELIVERY_VERDICTS})


def wake_roster_state(result_code: object) -> str | None:
    """Project one stored attempt result onto the compact roster vocabulary."""
    if result_code == WAKE_DELIVERED_RESULT:
        return "wake-delivered"
    if result_code == TURN_WITHOUT_INJECTION_RESULT:
        return "wake-undelivered"
    return resume_roster_state(result_code)


#: What an operator reading an undelivered wake should do about it.
TURN_WITHOUT_INJECTION_RECOVERY = (
    "The resumed turn ran no tool call, so no hook attached the envelope. "
    "The next wake for this receipt routes through a peer-hook broker; read "
    "the receipt with `yoke messages get <message-id>`."
)


__all__ = [
    "NATIVE_RESUME_ACCEPTED_RESULT",
    "WAKE_ATTEMPT_SUCCESS_RESULTS",
    "WAKE_ATTEMPT_ROSTER_RESULTS",
    "TURN_WITHOUT_INJECTION_RECOVERY",
    "TURN_WITHOUT_INJECTION_RESULT",
    "WAKE_DELIVERED_RESULT",
    "WAKE_DELIVERY_UNVERIFIED_RESULTS",
    "WAKE_DELIVERY_VERDICTS",
    "WAKE_REPORT_CODES",
    "wake_attempt_unsettled",
    "wake_roster_state",
]
