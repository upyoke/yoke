"""Named causes for a failed baseline probe, keyed by the sealed exit code.

The sealed standard probe programs exit with these codes and the classifier
reads the same table back, so a failure keeps its cause across the host
boundary instead of collapsing into one ambiguous non-zero exit.
"""

from __future__ import annotations

from dataclasses import dataclass

from yoke_harness.baseline_harness_requests import HarnessRequest


@dataclass(frozen=True)
class ProbeFailureCause:
    """One diagnosed failure: its stable cause, what happened, and the fix."""

    cause: str
    reason: str
    recovery: str


EXECUTABLE_MISSING = ProbeFailureCause(
    "probe_executable_missing",
    "no executable was found on the test user's PATH or in ~/.local/bin",
    "Install the harness for the test user, sign it in, then retry.",
)
REQUEST_TIMED_OUT = ProbeFailureCause(
    "probe_request_timed_out",
    "the probe's command did not finish within its time limit",
    "Check the host's network and the provider's status, then retry; if it "
    "persists, run the command by hand in the test user's GUI session to see "
    "where it stalls.",
)
LAUNCH_FAILED = ProbeFailureCause(
    "probe_launch_failed",
    "the executable was found but could not be started",
    "Repair the executable's permissions or reinstall it for the test user, "
    "then retry.",
)
HARNESS_EXIT_NONZERO = ProbeFailureCause(
    "probe_harness_exit_nonzero",
    "the harness ran the request and exited non-zero",
    "Run the harness by hand in the test user's GUI session to read its error; "
    "if it reports a missing or expired login, sign it in again, then retry.",
)
REPLY_UNANSWERED = ProbeFailureCause(
    "probe_reply_unanswered",
    "the harness exited 0 but its reply did not parse as a successful answer",
    "Check that the installed harness version still prints its stream-json "
    "reply and answers without tools, update it, then retry.",
)
CHECK_UNMET = ProbeFailureCause(
    "probe_check_unmet",
    "the check ran and the state it asserts is absent",
    "Restore the state the check names in the test user's session, capture a "
    "new golden, then retry.",
)

# The one code-to-cause table. Codes avoid 1 and 2, which Python itself uses
# for an uncaught exception and a usage error.
PROBE_FAILURE_CAUSES: dict[int, ProbeFailureCause] = {
    10: EXECUTABLE_MISSING,
    11: REQUEST_TIMED_OUT,
    12: LAUNCH_FAILED,
    13: HARNESS_EXIT_NONZERO,
    14: REPLY_UNANSWERED,
    15: CHECK_UNMET,
}
PROBE_EXIT_CODES: dict[str, int] = {
    failure.cause: code for code, failure in PROBE_FAILURE_CAUSES.items()
}

# A sealed standard probe exiting outside the table predates it or crashed.
UNDECLARED_EXIT = ProbeFailureCause(
    "probe_exit_undeclared",
    "the sealed probe program exited with a code that names no declared cause",
    "Capture a new golden so its sealed probes name their failure cause, then "
    "retry; a golden sealed before the cause table reports every failure as 1.",
)
# Operator-declared probes keep their own argv and expectation.
DECLARED_PROBE_EXIT_NONZERO = ProbeFailureCause(
    "probe_exit_nonzero",
    "the declared probe program exited non-zero",
    "Restore the state the probe checks and capture a new golden, or correct "
    "the probe argv in the document beside the golden.",
)
DECLARED_PROBE_EXPECTATION_UNMET = ProbeFailureCause(
    "probe_expectation_unmet",
    "the declared probe exited 0 but its output lacked the declared expectation",
    "Restore the state the probe checks and capture a new golden, or correct "
    "the probe expectation in the document beside the golden.",
)


def failure_evidence(
    failure: ProbeFailureCause, subject: str, recovery: str | None = None
) -> dict[str, str]:
    """Render one cause as the evidence fields a failed probe row carries."""
    step = recovery or failure.recovery
    return {
        "cause": failure.cause,
        "reason": f"{subject} failed: {failure.reason}. {step}",
        "recovery": step,
    }


def classify_declared_failure(
    name: str,
    exit_code: int,
    *,
    request: HarnessRequest | None,
    stdout: str,
    stderr: str,
) -> dict[str, str]:
    """Name a delivered failure of a probe the golden's document declares."""
    if request is not None:
        refusal = request.native_refusal(stdout, stderr)
        if refusal is not None:
            return refusal
        subject = f"{request.name} real request"
        if exit_code:
            return failure_evidence(HARNESS_EXIT_NONZERO, subject, request.recovery)
        return failure_evidence(REPLY_UNANSWERED, subject)
    if exit_code:
        return failure_evidence(DECLARED_PROBE_EXIT_NONZERO, name)
    return failure_evidence(DECLARED_PROBE_EXPECTATION_UNMET, name)


__all__ = [
    "CHECK_UNMET",
    "DECLARED_PROBE_EXIT_NONZERO",
    "DECLARED_PROBE_EXPECTATION_UNMET",
    "EXECUTABLE_MISSING",
    "HARNESS_EXIT_NONZERO",
    "LAUNCH_FAILED",
    "PROBE_EXIT_CODES",
    "PROBE_FAILURE_CAUSES",
    "REPLY_UNANSWERED",
    "REQUEST_TIMED_OUT",
    "UNDECLARED_EXIT",
    "ProbeFailureCause",
    "classify_declared_failure",
    "failure_evidence",
]
