"""Dispatch Machine QA operator gates, and the one gate a person finishes.

Each terminal backend calls ``run_operator_gate_with_io``; the run performs
every gate an agent can (browser approval, admission approval, invite entry).
A ``human_action`` gate is only a password or credential entry: it announces
that one step and where, sends no input, carries no secret, and only reads
the terminal until the declared completion text appears, the command exits,
a denial shows, or the bounded wait expires.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import json
from typing import Any

from yoke_harness.machine_browser_approval import BrowserApprovalResult
from yoke_harness.ssh_mac_browser_approval import approve_machine_in_safari

from yoke_core.domain.machine_qa_admission_gate import (
    RunYoke,
    run_admission_gate_with_io,
    yoke_runner,
)
from yoke_core.domain.machine_qa_operator_gate import (
    OperatorGateResult,
    await_gate_completion,
    run_machine_browser_approval_with_io,
)
from yoke_core.domain.machine_qa_operator_gate_contract import (
    ADMISSION_INVITE_ENTRY,
    ADMISSION_OWNER_APPROVAL,
    HUMAN_ACTION,
    MACHINE_BROWSER_APPROVAL,
)
from yoke_core.domain.ssh_mac_terminal_capture import RunRemote
from yoke_core.domain.ssh_mac_terminal_recipe_support import (
    capture_recipe_transcript,
    read_recipe_exit_code,
    send_recipe_keys,
)


def human_action_instructions(step: str, *, terminal_location: str) -> str:
    """Name the one password entry and where it happens, without any secret."""
    return (
        f"Step {step}: type your own password or credential where the terminal "
        f"at {terminal_location} or its browser asks for it. The agent did every "
        "other step; the run sends no keys and never receives what you type."
    )


def run_human_action_gate_with_io(
    *,
    read_transcript: Callable[[], str],
    read_exit_code: Callable[[str], int | None],
    action: Mapping[str, Any],
    progress_callback: Callable[[], None] | None,
    terminal_location: str,
) -> OperatorGateResult:
    """Announce the one password entry, then wait only for its outcome."""
    step = str(action["step"])
    timeout_seconds = int(float(action["gate_timeout_seconds"]))
    evidence: dict[str, Any] = {
        "human_purpose": str(action["human_purpose"]),
        "self_approving": False,
        "terminal_location": terminal_location,
        "timeout_seconds": timeout_seconds,
    }
    print(
        json.dumps(
            {
                "event": "machine_qa.operator_gate",
                "kind": HUMAN_ACTION,
                "instructions": human_action_instructions(
                    step, terminal_location=terminal_location
                ),
                **evidence,
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return await_gate_completion(
        gate=HUMAN_ACTION,
        read_transcript=read_transcript,
        read_exit_code=read_exit_code,
        action=action,
        progress_callback=progress_callback,
        evidence=evidence,
        code=None,
        timeout_recovery=(
            f"Nobody finished the password entry for step {step} within "
            f"{timeout_seconds} seconds. Rerun the case when the person is "
            "ready, and follow the announced instructions."
        ),
    )


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
    run_yoke: RunYoke,
    terminal_location: str,
) -> OperatorGateResult:
    """Run the action's registered gate through one terminal backend's I/O."""
    gate = action["operator_gate"]
    if gate in {ADMISSION_OWNER_APPROVAL, ADMISSION_INVITE_ENTRY}:
        return run_admission_gate_with_io(
            read_transcript=read_transcript,
            send_keys=send_keys,
            read_exit_code=read_exit_code,
            run_yoke=run_yoke,
            action=action,
            progress_callback=progress_callback,
        )
    if gate == MACHINE_BROWSER_APPROVAL:
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
    yoke_bin: str,
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
        run_yoke=yoke_runner(run, yoke_bin),
        terminal_location=f"the visible Terminal window on the test machine ({attach})",
    )


__all__ = [
    "human_action_instructions",
    "run_human_action_gate_with_io",
    "run_multiplexer_operator_gate",
    "run_operator_gate_with_io",
]
