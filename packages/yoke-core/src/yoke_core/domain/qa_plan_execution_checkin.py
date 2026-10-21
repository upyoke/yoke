"""Bounded check-in delivery using the dispatcher's exact-request ledger."""

from __future__ import annotations

import sys
import time
from uuid import uuid4

from yoke_core.domain.function_lock_refusal import (
    LOCK_RETRY_DELAYS_SECONDS,
    RETRYABLE_LOCK_CODES,
)
from yoke_core.domain.qa_plan_execution_result_state import QaPlanExecutionError
from yoke_core.domain.qa_case_execution import QaCaseExecutionError


CHECKIN_RESPONSE_SECONDS = 5.0


class QaPlanCommunicationUnknown(QaPlanExecutionError, QaCaseExecutionError):
    """Delivery stopped without proving the execution operation failed."""

    def __init__(self, *, function_id, request_id, attempts):
        self.function_id = function_id
        self.request_id = request_id
        self.attempts = attempts
        self.evidence_path = None
        super().__init__(
            f"qa_communication_outcome_unknown: {function_id} request {request_id}; "
            "preserve this execution and inspect its durable cursor before re-entry"
        )


def communication_unknown(error):
    """Keep communication identity through host-runner exception wrappers."""
    while error is not None:
        if isinstance(error, QaPlanCommunicationUnknown):
            return error
        error = error.__cause__
    return None


class QaPlanStopRequested(QaPlanExecutionError):
    """A recorded stop request: the walk stops and its runner settles it."""


def checkin_refused(error):
    """Whether a check-in refusal ends the walk without aborting it.

    A recorded stop is not a refusal: the runner aborts the execution so the
    request settles instead of leaving it live.
    """
    return isinstance(error, QaPlanExecutionError) and not isinstance(
        error, QaPlanStopRequested
    )


def stop_if_told(checked, execution):
    """Stop the walk when its check-in says the walk must not go on.

    A recorded stop -- the owner's host abort, a steering seat's stop, or a
    member removal -- stops it outright, and the runner then aborts the
    execution itself so its host is cleaned up and the execution settles. A
    moved roster digest means a case this walk has not reached was corrected
    after it began; the copy this walker holds is stale, and resuming reads
    the corrected one.
    """
    if checked.get("abort_requested"):
        raise QaPlanStopRequested(
            "qa_stop_requested: a stop is recorded for this execution; this walk "
            "stopped and aborts it under the recorded reason"
        )
    current = checked.get("roster_digest")
    if current and current != execution.get("roster_digest"):
        raise QaPlanExecutionError(
            f"qa_roster_corrected: a case execution {execution['execution_id']} "
            "had not reached yet was corrected after this walk began. Run the "
            "same `yoke qa plan run` command again: it resumes at the cursor "
            "with the corrected cases and keeps every recorded result."
        )


def deliver_plan_function(*, function_id, target, payload, actor):
    from yoke_core.domain.qa_composed_dispatch import call_qa_function

    request_id = str(uuid4())
    attempts = []
    # Only liveness may retry. The same request id reconciles a late success
    # through the existing durable ledger before another check-in executes.
    count = 2 if function_id == "qa.plan_execution.heartbeat" else 1
    # A busy answer is definite and ran nothing, so it repeats on the shared
    # backoff under a fresh request id rather than failing the walk.
    busy_delays = iter(LOCK_RETRY_DELAYS_SECONDS)
    busy_attempts = 0
    attempt = 0
    while attempt < count:
        if attempt:
            time.sleep(0.25)
        response = call_qa_function(
            function_id=function_id,
            target=target,
            payload=payload,
            actor=actor,
            request_id=request_id,
            **(
                {"timeout_s": CHECKIN_RESPONSE_SECONDS}
                if function_id
                in {"qa.plan_execution.heartbeat", "qa.plan_execution.pause"}
                else {}
            ),
        )
        if response.success:
            result = dict(response.result or {})
            if attempts:
                result["delivery"] = {
                    "request_id": request_id,
                    "attempts": attempts + [{"outcome": "accepted"}],
                }
            return result
        code = response.error.code if response.error else "unknown"
        message = response.error.message if response.error else ""
        recovery = response.error.recovery_hint if response.error else ""
        if code in RETRYABLE_LOCK_CODES:
            busy_attempts += 1
            delay = next(busy_delays, None)
            if delay is None:
                raise QaPlanExecutionError(
                    f"run_busy_retries_exhausted: {function_id} was refused as "
                    f"busy on all {busy_attempts} attempts ({code}): {message} "
                    "Re-run the same command once the holder named above finishes."
                )
            print(
                f"{function_id} answered {code}; asking again in {delay:g}s "
                f"(attempt {busy_attempts + 1} of {len(LOCK_RETRY_DELAYS_SECONDS) + 1})",
                file=sys.stderr,
                flush=True,
            )
            time.sleep(delay)
            request_id = str(uuid4())
            continue
        if code != "https_transport_failed":
            raise QaPlanExecutionError(
                f"{function_id} failed ({code}): {message}. {recovery or ''}"
            )
        attempts.append({"outcome": code, "message": message})
        attempt += 1
    unknown = QaPlanCommunicationUnknown(
        function_id=function_id, request_id=request_id, attempts=attempts
    )
    from yoke_cli.transport.response_evidence import save_response
    from yoke_core.domain.machine_qa_submission_artifacts import (
        ensure_secret_free_result,
    )

    try:
        ensure_secret_free_result(payload)
        unknown.evidence_path = str(
            save_response(
                {
                    "function": function_id,
                    "request_id": request_id,
                    "target": target.model_dump(mode="json"),
                    "payload": payload,
                    "attempts": attempts,
                },
                "",
                "",
            )
        )
    except (OSError, ValueError) as evidence_error:
        unknown.add_note(
            f"qa_unknown_evidence_unavailable: {evidence_error}; preserve the command capture"
        )
    if unknown.evidence_path:
        unknown.args = (f"{unknown}. Saved request evidence: {unknown.evidence_path}",)
    raise unknown


def paused_result(*, error, call, execution, target, actor, phase, cursor, results):
    evidence = {
        "execution_id": str(execution["execution_id"]),
        "phase": phase,
        "cursor": cursor,
        "request_id": error.request_id,
        "attempts": error.attempts,
        "evidence_path": error.evidence_path,
        "capture_path": getattr(error, "capture_path", None),
    }
    recovery_file = None
    if error.evidence_path:
        import json
        from pathlib import Path

        try:
            capture = Path(error.evidence_path)
            saved = json.loads(capture.read_text())
            saved["pause"] = evidence
            capture.write_text(json.dumps(saved, ensure_ascii=False, indent=2) + "\n")
            recovery_file = error.evidence_path
        except (OSError, ValueError) as capture_error:
            evidence["capture_error"] = (
                f"qa_pause_receipt_unavailable: {capture_error}; preserve the command capture"
            )
    pause = "unconfirmed"
    try:
        call(
            function_id="qa.plan_execution.pause",
            target=target,
            payload={
                key: value for key, value in evidence.items() if key != "capture_error"
            },
            actor=actor,
        )
        pause = "recorded"
    except QaPlanExecutionError as pause_error:
        evidence["pause_error"] = str(pause_error)
    return {
        "execution_id": evidence["execution_id"],
        "state": "outcome_unknown",
        "reason": "qa_communication_outcome_unknown",
        "phase": phase,
        "cursor_ordinal": cursor,
        "results": results,
        "executed_count": len(results),
        "communication": evidence,
        "pause": pause,
        "recovery": (
            "Communication stopped; no failure verdict or abort was recorded. "
            "Keep the owning session and custody. Restore communication, then use "
            "the same subject and source arguments with --resume-execution-id "
            f"{evidence['execution_id']}"
            + (f" --recovery-file {recovery_file}. " if recovery_file else ". ")
            + "Re-entry validates the exact cursor and custody; "
            "an unrecorded case action requires inspecting and recording its saved "
            "outcome first. Never reset, replay an action, or create a new campaign."
        ),
    }


def restore_confirmed_pause(path, *, call, target, actor, execution_id):
    """Reapply the saved safe pause after connectivity returns, never an action."""
    import json
    from pathlib import Path

    try:
        saved = json.loads(Path(path).read_text())
        evidence = dict(saved["pause"])
        if evidence["execution_id"] != execution_id or evidence["phase"] != "checkin":
            raise ValueError(
                "only a pre-case check-in receipt can authorize safe re-entry"
            )
        if saved["response"]["target"] != target.model_dump(mode="json"):
            raise ValueError("the saved request names another subject")
        if (
            saved["response"]["request_id"] != evidence["request_id"]
            or saved["response"]["payload"].get("execution_id") != execution_id
        ):
            raise ValueError(
                "the saved request identity differs from its pause receipt"
            )
        if saved["response"]["function"] != "qa.plan_execution.heartbeat":
            raise ValueError("the saved request is not a check-in")
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise QaPlanExecutionError(
            f"qa_recovery_receipt_invalid: {error}; preserve the capture and ask the control-plane operator to reconcile this execution"
        ) from error
    return call(
        function_id="qa.plan_execution.pause",
        target=target,
        payload=evidence,
        actor=actor,
    )
