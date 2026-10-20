"""Typed operator handoffs inside credential-local Machine QA execution."""

from __future__ import annotations

from yoke_core.domain.qa_plan_execution_checkin import communication_unknown

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import json
import time
from typing import Any
from urllib.parse import urlsplit

from yoke_contracts.machine_approval_coordinates import machine_approval_coordinates
from yoke_contracts.machine_authorization import MATCH_CODE_LABEL

from yoke_core.domain.machine_qa_phase_heartbeat import (
    HEARTBEAT_SECONDS,
    MachineQaAborted,
    emit_heartbeat_line,
)
from yoke_core.domain.machine_qa_setup_exit import step_failure
from yoke_harness.machine_browser_approval import BrowserApprovalResult


BROWSER_APPROVAL_NOT_CONFIRMED = "machine_browser_approval_not_confirmed"
DENIAL_MARKERS = (
    "authorization denied in the browser",
    "authorization expired",
    "hosted authorization expired",
    "this machine was denied in the browser",
)


@dataclass(frozen=True)
class OperatorGateResult:
    """Outcome of one typed operator handoff."""

    ok: bool
    transcript: str
    error_code: str | None = None
    browser_evidence: dict[str, Any] | None = None
    browser_automation_error_code: str | None = None
    step_evidence: dict[str, Any] | None = None


def labeled_value(transcript: str, label: str) -> str | None:
    for line in transcript.splitlines():
        stripped = line.strip().lstrip("-•*").lstrip()
        if stripped.startswith(label):
            value = stripped.removeprefix(label).strip()
            if value:
                return value
    return None


def _approved_origin(origin: str, allowed_base_urls: tuple[str, ...]) -> bool:
    return any(
        origin == f"{allowed.scheme}://{allowed.netloc}"
        for allowed in (urlsplit(value) for value in allowed_base_urls)
    )


def current_gate_transcript(transcript: str, code: str) -> str:
    """Exclude retained output from machine approvals that preceded this code."""

    code_index = transcript.rfind(code)
    return transcript[code_index:] if code_index >= 0 else transcript


def _emit_browser_approval(url: str, code: str, browser: str) -> None:
    print(
        json.dumps(
            {
                "approval_automation": f"self_approving_visible_{browser.casefold()}",
                "event": "machine_qa.operator_gate",
                "kind": "machine_browser_approval",
                "self_approving": True,
                "url": url,
                "code": code,
            },
            sort_keys=True,
        ),
        flush=True,
    )


def gate_exit_result(
    action: Mapping[str, Any],
    transcript: str,
    read_exit_code: Callable[[str], int | None],
    browser_evidence: dict[str, Any] | None = None,
) -> OperatorGateResult | None:
    exit_code = read_exit_code(transcript)
    if exit_code is None:
        return None
    error_code, evidence = step_failure(
        str(action["step"]),
        waiting_for=list(action["completion_text"]),
        transcript=transcript,
        exit_code=exit_code,
    )
    return OperatorGateResult(
        False,
        transcript,
        error_code,
        browser_evidence,
        step_evidence=evidence,
    )


def run_machine_browser_approval_with_io(
    *,
    read_transcript: Callable[[], str],
    send_keys: Callable[[Sequence[str]], bool],
    read_exit_code: Callable[[str], int | None],
    action: Mapping[str, Any],
    progress_callback: Callable[[], None] | None,
    allowed_base_urls: tuple[str, ...],
    browser: str,
    approve_browser: Callable[[str, str], BrowserApprovalResult],
) -> OperatorGateResult:
    """Run one browser handoff through an already-authorized terminal surface.

    ``read_exit_code`` reports how the command under the terminal exited, so a
    setup that stopped before or during approval is named by its own exit.
    """
    transcript = read_transcript()
    url = labeled_value(transcript, "Open:")
    code = labeled_value(transcript, MATCH_CODE_LABEL)
    if url is None or code is None:
        exited = gate_exit_result(action, transcript, read_exit_code)
        if exited is not None:
            return exited
        return OperatorGateResult(
            False,
            transcript,
            "machine_browser_approval_context_missing",
        )
    try:
        coordinates = machine_approval_coordinates(url, code)
        if not _approved_origin(coordinates.origin, allowed_base_urls):
            raise ValueError(
                "machine approval origin is outside the declared execution target"
            )
    except ValueError as exc:
        return OperatorGateResult(
            False,
            transcript,
            "machine_browser_approval_context_invalid",
            browser_evidence={
                "context_refusal": str(exc),
                "recovery": "Capture the live code and its matching verification URI from the declared target, then rerun the case.",
            },
        )
    url, code = coordinates.complete_uri, coordinates.user_code
    _emit_browser_approval(url, code, browser)
    if action["keys"] and not send_keys(action["keys"]):
        return OperatorGateResult(
            False,
            transcript,
            "machine_browser_approval_input_failed",
        )
    approval = approve_browser(url, code)
    if not approval.ok:
        # The helper could not confirm the approval in its tab, so nothing can
        # finish this gate: the terminal would only poll until it timed out.
        browser_automation_error_code = (
            approval.error_code or "machine_browser_approval_failed"
        )
        return OperatorGateResult(
            False,
            read_transcript(),
            BROWSER_APPROVAL_NOT_CONFIRMED,
            approval.evidence,
            browser_automation_error_code,
            step_evidence={
                "browser_automation_error_code": browser_automation_error_code,
                "recovery": (
                    "The browser helper did not confirm the approval in its "
                    "tab, so the gate stopped without waiting out its timeout. "
                    "Read browser_approval for where it stopped, repair that "
                    "on the test machine, then rerun the case."
                ),
            },
        )
    timeout_seconds = float(action["gate_timeout_seconds"])
    completion_text = tuple(action["completion_text"])
    gate_code = labeled_value(transcript, MATCH_CODE_LABEL)
    assert gate_code is not None
    started = time.monotonic()
    deadline = started + timeout_seconds
    next_heartbeat = 0.0
    while True:
        transcript = read_transcript()
        gate_transcript = current_gate_transcript(transcript, gate_code)
        lowered = gate_transcript.casefold()
        if all(marker in gate_transcript for marker in completion_text):
            return OperatorGateResult(
                True,
                transcript,
                browser_evidence=approval.evidence,
            )
        if any(marker in lowered for marker in DENIAL_MARKERS):
            return OperatorGateResult(
                False,
                transcript,
                "machine_browser_approval_rejected",
                approval.evidence,
            )
        exited = gate_exit_result(
            action, gate_transcript, read_exit_code, approval.evidence
        )
        if exited is not None:
            return exited
        now = time.monotonic()
        if now >= deadline:
            return OperatorGateResult(
                False,
                transcript,
                "machine_browser_approval_timed_out",
                approval.evidence,
            )
        if now >= next_heartbeat:
            emit_heartbeat_line(
                "operator_gate",
                now - started,
                step=str(action["step"]),
                timeout_seconds=int(timeout_seconds),
            )
            if progress_callback is not None:
                try:
                    progress_callback()
                except Exception as error:
                    if isinstance(error, MachineQaAborted):
                        raise
                    if communication_unknown(error):
                        raise
                    return OperatorGateResult(
                        False,
                        transcript,
                        "machine_browser_approval_heartbeat_failed",
                        approval.evidence,
                    )
            next_heartbeat = now + HEARTBEAT_SECONDS
        time.sleep(1.0)


def gate_failure(
    error_code: str,
    transcript: str,
    evidence: Mapping[str, Any],
    recovery: str,
) -> OperatorGateResult:
    """Refuse one gate with its evidence and the recovery step."""
    return OperatorGateResult(
        False,
        transcript,
        error_code,
        step_evidence={**evidence, "recovery": recovery},
    )


def await_gate_completion(
    *,
    gate: str,
    read_transcript: Callable[[], str],
    read_exit_code: Callable[[str], int | None],
    action: Mapping[str, Any],
    progress_callback: Callable[[], None] | None,
    evidence: dict[str, Any],
    code: str | None,
    timeout_recovery: str,
) -> OperatorGateResult:
    """Read the terminal until the step completes, is denied, exits or expires."""
    timeout_seconds = float(action["gate_timeout_seconds"])
    completion_text = tuple(action["completion_text"])
    started = time.monotonic()
    deadline = started + timeout_seconds
    next_heartbeat = 0.0
    while True:
        transcript = read_transcript()
        gate_transcript = (
            current_gate_transcript(transcript, code) if code else transcript
        )
        now = time.monotonic()
        evidence["waited_seconds"] = int(now - started)
        if all(marker in gate_transcript for marker in completion_text):
            return OperatorGateResult(True, transcript, step_evidence=evidence)
        if any(marker in gate_transcript.casefold() for marker in DENIAL_MARKERS):
            return gate_failure(
                f"{gate}_rejected",
                transcript,
                evidence,
                "The terminal reported the admission was denied or expired. "
                "Read the transcript, then rerun the case.",
            )
        exited = gate_exit_result(action, gate_transcript, read_exit_code)
        if exited is not None:
            return exited
        if now >= deadline:
            return gate_failure(
                f"{gate}_timed_out", transcript, evidence, timeout_recovery
            )
        if now >= next_heartbeat:
            emit_heartbeat_line(
                "operator_gate",
                now - started,
                step=str(action["step"]),
                operator_gate=gate,
                timeout_seconds=int(timeout_seconds),
            )
            if progress_callback is not None:
                try:
                    progress_callback()
                except Exception as error:
                    if isinstance(error, MachineQaAborted) or communication_unknown(
                        error
                    ):
                        raise
                    return gate_failure(
                        f"{gate}_heartbeat_failed",
                        transcript,
                        evidence,
                        "The run could not renew its host lease while waiting. "
                        "Restore the control-plane connection, then rerun.",
                    )
            next_heartbeat = now + HEARTBEAT_SECONDS
        time.sleep(1.0)


__all__ = [
    "BROWSER_APPROVAL_NOT_CONFIRMED",
    "DENIAL_MARKERS",
    "OperatorGateResult",
    "await_gate_completion",
    "current_gate_transcript",
    "gate_exit_result",
    "gate_failure",
    "labeled_value",
    "run_machine_browser_approval_with_io",
]
