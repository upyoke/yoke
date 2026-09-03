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

from typing import Any, Mapping

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


#: Named when a failed attempt carried nothing more specific. A code with
#: no reason behind it is the shape this whole helper exists to stop: an
#: operator watching `failed` with an empty diagnostic column cannot tell a
#: refused instruction from a dead binary, and four steering waits were
#: abandoned by hand while every attempt behind them read exactly that.
UNREPORTED_DELIVERY_DIAGNOSTIC = "unreported"

#: Evidence keys carrying a named reason, most specific first. `result_code`
#: is the adapter's own refusal code, which is finer than the attempt row's
#: coarse `failed`; `skip_reason` names the eligibility rule that declined a
#: route; `closure_reason` names a server-side closure; `probe_detail` and
#: `transport_result` carry what the two remaining failure shapes saw.
_DIAGNOSTIC_EVIDENCE_KEYS = (
    "result_code",
    "skip_reason",
    "closure_reason",
    "probe_detail",
    "transport_result",
)


#: What the hook route reports when it attached the envelope itself. It is
#: the other half of the delivered vocabulary: an attempts table carries
#: both routes, so a reader that knows only the wake codes would call every
#: successful hook injection a failure.
HOOK_INJECTED_RESULT = "injected"

#: Every attempt outcome, on either route, that delivered or may still.
DELIVERY_ATTEMPT_SUCCESS_RESULTS = frozenset(
    {HOOK_INJECTED_RESULT, *WAKE_ATTEMPT_SUCCESS_RESULTS}
)


def delivery_attempt_failed(result_code: object) -> bool:
    """True when this attempt did not deliver and never will.

    An attempt with no result yet is in flight, not failed: the control
    plane settles the delivery verdict after the relay reports, so a blank
    code is a question still open rather than an answer.
    """
    if result_code is None or not str(result_code).strip():
        return False
    return str(result_code) not in DELIVERY_ATTEMPT_SUCCESS_RESULTS


def delivery_attempt_diagnostic(
    result_code: object,
    evidence: Mapping[str, Any] | None,
) -> str:
    """Return the named reason a delivery attempt failed, never empty.

    The attempt row stores a coarse outcome — `failed` covers a refused
    instruction, a missing binary, a resume that would not spawn, and a
    native that raised. The reason is in the evidence, and for two hours
    every wake on one machine refused for the same nameable cause while the
    operator-facing table showed `failed` against an empty column. So every
    reader of a failed attempt goes through here, and an attempt that
    reports nothing at all still says so out loud.
    """
    if not delivery_attempt_failed(result_code):
        return ""
    document = evidence if isinstance(evidence, Mapping) else {}
    coarse = str(result_code)
    named = ""
    for key in _DIAGNOSTIC_EVIDENCE_KEYS:
        value = document.get(key)
        if isinstance(value, str) and value.strip() and value.strip() != coarse:
            named = value.strip()
            break
    reference = document.get("native_diagnostic_ref")
    if not named and isinstance(reference, str) and reference.strip():
        named = reference.strip()
    # The native's own last line, beside the coded reason rather than instead
    # of it. The capture behind the reference is readable only on the machine
    # that produced it, so a reader anywhere else has this line or nothing.
    tail = document.get("native_stderr_tail")
    said = tail.strip() if isinstance(tail, str) else ""
    if named and said:
        return f"{named}: {said}"
    return named or said or UNREPORTED_DELIVERY_DIAGNOSTIC


#: What an operator reading an undelivered wake should do about it.
TURN_WITHOUT_INJECTION_RECOVERY = (
    "The resumed turn ran no tool call, so no hook attached the envelope. "
    "The next wake for this receipt routes through a peer-hook broker; read "
    "the receipt with `yoke messages get <message-id>`."
)


__all__ = [
    "DELIVERY_ATTEMPT_SUCCESS_RESULTS",
    "HOOK_INJECTED_RESULT",
    "NATIVE_RESUME_ACCEPTED_RESULT",
    "UNREPORTED_DELIVERY_DIAGNOSTIC",
    "delivery_attempt_diagnostic",
    "delivery_attempt_failed",
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
