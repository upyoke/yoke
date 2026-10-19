"""The non-self-approving Machine QA gate: a bounded wait for one human step.

A ``human_action`` gate announces what the person must do and where, sends
no input to the terminal, carries no secret, and never calls approval
automation. It only reads the terminal until the declared completion text
appears, the command exits, a denial shows, or the bounded wait expires.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import json
import re
import time
from typing import Any

from yoke_contracts.machine_authorization import MATCH_CODE_LABEL, MATCH_CODE_PATTERN
from yoke_harness.machine_browser_approval import BrowserApprovalResult
from yoke_harness.ssh_mac_browser_approval import approve_machine_in_safari

from yoke_core.domain.machine_qa_operator_gate import (
    DENIAL_MARKERS,
    OperatorGateResult,
    current_gate_transcript,
    gate_exit_result,
    labeled_value,
    run_machine_browser_approval_with_io,
)
from yoke_core.domain.machine_qa_operator_gate_contract import (
    HUMAN_ACTION,
    MACHINE_BROWSER_APPROVAL,
)
from yoke_core.domain.machine_qa_phase_heartbeat import (
    HEARTBEAT_SECONDS,
    emit_heartbeat_line,
)
from yoke_core.domain.qa_plan_execution_checkin import communication_unknown
from yoke_core.domain.ssh_mac_terminal_capture import RunRemote
from yoke_core.domain.ssh_mac_terminal_recipe_support import (
    capture_recipe_transcript,
    read_recipe_exit_code,
    send_recipe_keys,
)


_MATCH_CODE = re.compile(MATCH_CODE_PATTERN)
_CODED_PURPOSES = frozenset({"company_sign_in", "machine_approval"})


def human_action_instructions(
    purpose: str, *, terminal_location: str, code: str | None
) -> str:
    """Name the one human step and where it happens, without any secret."""
    if purpose == "machine_approval":
        return (
            f"Approve match code {code} as the person who owns this "
            "connection, from their already-connected machine: "
            f"yoke machines approve {code}. The run never approves it."
        )
    if purpose == "private_invite_entry":
        return (
            "As the inviter, run yoke invite NAME on an already-connected "
            "machine, then type the code privately into the terminal at "
            f"{terminal_location}. The run sends no keys and never receives "
            "the code."
        )
    return (
        "In the test machine's browser, open the approval link the terminal "
        "shows (the full-screen wizard opens it for you), sign in as the "
        f"teammate, confirm match code {code} and approve this machine; the "
        f"terminal at {terminal_location} continues by itself."
    )


def _failure(
    error_code: str,
    transcript: str,
    evidence: Mapping[str, Any],
    recovery: str,
) -> OperatorGateResult:
    return OperatorGateResult(
        False,
        transcript,
        error_code,
        step_evidence={**evidence, "recovery": recovery},
    )


def run_human_action_gate_with_io(
    *,
    read_transcript: Callable[[], str],
    read_exit_code: Callable[[str], int | None],
    action: Mapping[str, Any],
    progress_callback: Callable[[], None] | None,
    terminal_location: str,
) -> OperatorGateResult:
    """Announce one typed human step, then wait only for its outcome."""
    purpose = str(action["human_purpose"])
    timeout_seconds = float(action["gate_timeout_seconds"])
    evidence: dict[str, Any] = {
        "human_purpose": purpose,
        "self_approving": False,
        "terminal_location": terminal_location,
        "timeout_seconds": int(timeout_seconds),
    }
    transcript = read_transcript()
    code: str | None = None
    if purpose in _CODED_PURPOSES:
        code = (labeled_value(transcript, MATCH_CODE_LABEL) or "").upper()
        if not _MATCH_CODE.fullmatch(code):
            exited = gate_exit_result(action, transcript, read_exit_code)
            if exited is not None:
                return exited
            return _failure(
                "human_action_context_missing",
                transcript,
                evidence,
                "The terminal showed no match code to approve. Make the "
                "preceding step wait for the code screen, then rerun the case.",
            )
        evidence["code"] = code
    instructions = human_action_instructions(
        purpose, terminal_location=terminal_location, code=code
    )
    print(
        json.dumps(
            {
                "event": "machine_qa.operator_gate",
                "kind": HUMAN_ACTION,
                "instructions": instructions,
                **evidence,
            },
            sort_keys=True,
        ),
        flush=True,
    )
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
            return _failure(
                "human_action_rejected",
                transcript,
                evidence,
                "The terminal reported the admission was denied or expired. "
                "Read the transcript, then rerun the case and finish the step "
                "before the code expires.",
            )
        exited = gate_exit_result(action, gate_transcript, read_exit_code)
        if exited is not None:
            return exited
        if now >= deadline:
            return _failure(
                "human_action_timed_out",
                transcript,
                evidence,
                f"Nobody finished the {purpose} step within "
                f"{int(timeout_seconds)} seconds. Rerun the case when the "
                "person is ready, and follow the announced instructions.",
            )
        if now >= next_heartbeat:
            emit_heartbeat_line(
                "operator_gate",
                now - started,
                step=str(action["step"]),
                human_purpose=purpose,
                timeout_seconds=int(timeout_seconds),
            )
            if progress_callback is not None:
                try:
                    progress_callback()
                except Exception as error:
                    if communication_unknown(error):
                        raise
                    return _failure(
                        "human_action_heartbeat_failed",
                        transcript,
                        evidence,
                        "The run could not renew its host lease while waiting. "
                        "Restore the control-plane connection, then rerun.",
                    )
            next_heartbeat = now + HEARTBEAT_SECONDS
        time.sleep(1.0)


def run_operator_gate_with_io(
    *,
    read_transcript: Callable[[], str],
    send_keys: Callable[[Sequence[str]], bool],
    read_exit_code: Callable[[str], int | None],
    action: Mapping[str, Any],
    progress_callback: Callable[[], None] | None,
    allowed_base_urls: tuple[str, ...],
    browser: str,
    approve_browser: Callable[[str, str], BrowserApprovalResult],
    terminal_location: str,
) -> OperatorGateResult:
    """Run the action's registered gate through one terminal backend's I/O."""
    if action["operator_gate"] == MACHINE_BROWSER_APPROVAL:
        return run_machine_browser_approval_with_io(
            read_transcript=read_transcript,
            send_keys=send_keys,
            read_exit_code=read_exit_code,
            action=action,
            progress_callback=progress_callback,
            allowed_base_urls=allowed_base_urls,
            browser=browser,
            approve_browser=approve_browser,
        )
    return run_human_action_gate_with_io(
        read_transcript=read_transcript,
        read_exit_code=read_exit_code,
        action=action,
        progress_callback=progress_callback,
        terminal_location=terminal_location,
    )


def run_multiplexer_operator_gate(
    run: RunRemote,
    *,
    backend: str,
    session: str,
    status_path: str,
    action: Mapping[str, Any],
    progress_callback: Callable[[], None] | None,
    allowed_base_urls: tuple[str, ...],
) -> OperatorGateResult:
    """Run the gate through a macOS tmux or screen session."""
    attach = (
        f"tmux attach-session -t {session}"
        if backend == "tmux"
        else f"screen -r {session}"
    )
    return run_operator_gate_with_io(
        read_transcript=lambda: capture_recipe_transcript(
            run, backend=backend, session=session
        ),
        send_keys=lambda keys: send_recipe_keys(
            run, backend=backend, session=session, keys=keys
        ),
        read_exit_code=lambda _transcript: read_recipe_exit_code(
            run, status_path=status_path
        ),
        action=action,
        progress_callback=progress_callback,
        allowed_base_urls=allowed_base_urls,
        browser="Safari",
        approve_browser=lambda url, code: approve_machine_in_safari(
            run, verification_url=url, user_code=code
        ),
        terminal_location=f"the visible Terminal window on the test machine ({attach})",
    )


__all__ = [
    "human_action_instructions",
    "run_human_action_gate_with_io",
    "run_multiplexer_operator_gate",
    "run_operator_gate_with_io",
]
