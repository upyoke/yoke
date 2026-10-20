"""Admission steps the run performs as the admission fixture's owner.

The machine admission fixture's owner is an already-connected machine home on
the test machine (``machine_qa_admission_host.approver_home``). These gates do
the owner's part of a journey through the installed candidate's own CLI:
``admission_owner_approval`` approves the match code the terminal shows with
``yoke machines approve``, and ``admission_invite_entry`` issues the
teammate's invite with ``yoke invite`` and types its code into the terminal.
Neither gate writes the invite code to evidence.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import json
import re
import shlex
import subprocess
from typing import Any

from yoke_contracts.machine_authorization import MATCH_CODE_LABEL, MATCH_CODE_PATTERN
from yoke_contracts.machine_config.paths import HOME_ENV as MACHINE_HOME_ENV
from yoke_contracts.machine_qa_failures import bounded_machine_qa_diagnostic

from yoke_core.domain.machine_qa_admission_host import TEAMMATE_NAME, approver_home
from yoke_core.domain.machine_qa_operator_gate import (
    OperatorGateResult,
    await_gate_completion,
    gate_exit_result,
    gate_failure,
    labeled_value,
)
from yoke_core.domain.machine_qa_operator_gate_contract import (
    ADMISSION_OWNER_APPROVAL,
)

RunYoke = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]
_MATCH_CODE = re.compile(MATCH_CODE_PATTERN)
_OWNER_MODE = "self-hosted"
_COMMAND_TIMEOUT_SECONDS = 120


def yoke_runner(
    run: Callable[..., subprocess.CompletedProcess[str]], yoke_bin: str
) -> RunYoke:
    """Run the installed candidate's ``yoke`` as the admission fixture's owner."""
    home = shlex.quote(str(approver_home(_OWNER_MODE)))

    def run_yoke(arguments: Sequence[str]) -> subprocess.CompletedProcess[str]:
        return run(
            f"{MACHINE_HOME_ENV}={home} " + shlex.join([yoke_bin, *arguments]),
            timeout=_COMMAND_TIMEOUT_SECONDS,
        )

    return run_yoke


def _command_failure(
    error_code: str,
    transcript: str,
    evidence: Mapping[str, Any],
    command: str,
    result: subprocess.CompletedProcess[str],
    secret_values: Sequence[str] = (),
) -> OperatorGateResult:
    return gate_failure(
        error_code,
        transcript,
        {
            **evidence,
            "command": command,
            "exit_code": result.returncode,
            "stderr": bounded_machine_qa_diagnostic(
                result.stderr or result.stdout, secret_values
            ),
        },
        f"The owner's `{command}` failed on the test machine. Read stderr, "
        "confirm the admission fixture's server is still serving (its "
        "server.log under the fixture root), then rerun the case.",
    )


def _approve_owner_code(
    transcript: str,
    evidence: dict[str, Any],
    run_yoke: RunYoke,
) -> tuple[str | None, OperatorGateResult | None]:
    code = (labeled_value(transcript, MATCH_CODE_LABEL) or "").upper()
    if not _MATCH_CODE.fullmatch(code):
        return None, gate_failure(
            "admission_owner_approval_context_missing",
            transcript,
            evidence,
            "The terminal showed no match code to approve. Make the preceding "
            "step wait for the code screen, then rerun the case.",
        )
    evidence["code"] = code
    result = run_yoke(["machines", "approve", code])
    if result.returncode != 0:
        return None, _command_failure(
            "admission_owner_approval_failed",
            transcript,
            evidence,
            "yoke machines approve CODE",
            result,
        )
    return code, None


def _enter_invite_code(
    transcript: str,
    evidence: dict[str, Any],
    run_yoke: RunYoke,
    send_keys: Callable[[Sequence[str]], bool],
) -> OperatorGateResult | None:
    command = f"yoke invite '{TEAMMATE_NAME}' --json"
    result = run_yoke(["invite", TEAMMATE_NAME, "--json"])
    try:
        invite_code = str(json.loads(result.stdout)["result"]["code"])
    except (ValueError, KeyError, TypeError):
        invite_code = ""
    if result.returncode != 0 or not invite_code:
        return _command_failure(
            "admission_invite_issue_failed",
            transcript,
            evidence,
            command,
            result,
            (invite_code,) if invite_code else (),
        )
    if not send_keys([invite_code, "Enter"]):
        return gate_failure(
            "admission_invite_input_failed",
            transcript,
            evidence,
            "The run could not type the invite code into the terminal. Repair "
            "the terminal session on the test machine, then rerun the case.",
        )
    evidence["invite_entered"] = True
    return None


def run_admission_gate_with_io(
    *,
    read_transcript: Callable[[], str],
    send_keys: Callable[[Sequence[str]], bool],
    read_exit_code: Callable[[str], int | None],
    run_yoke: RunYoke,
    action: Mapping[str, Any],
    progress_callback: Callable[[], None] | None,
) -> OperatorGateResult:
    """Do the owner's admission step, then wait for the journey to continue."""
    gate = str(action["operator_gate"])
    evidence: dict[str, Any] = {
        "self_approving": True,
        "acting_as": "admission fixture owner",
        "timeout_seconds": int(float(action["gate_timeout_seconds"])),
    }
    transcript = read_transcript()
    code: str | None = None
    if gate == ADMISSION_OWNER_APPROVAL:
        code, failed = _approve_owner_code(transcript, evidence, run_yoke)
    else:
        failed = _enter_invite_code(transcript, evidence, run_yoke, send_keys)
    if failed is not None:
        return gate_exit_result(action, transcript, read_exit_code) or failed
    print(
        json.dumps(
            {"event": "machine_qa.operator_gate", "kind": gate, **evidence},
            sort_keys=True,
        ),
        flush=True,
    )
    return await_gate_completion(
        gate=gate,
        read_transcript=read_transcript,
        read_exit_code=read_exit_code,
        action=action,
        progress_callback=progress_callback,
        evidence=evidence,
        code=code,
        timeout_recovery=(
            "The journey did not continue after the owner's step. Read the "
            "transcript for where setup stopped, then rerun the case."
        ),
    )


__all__ = ["RunYoke", "run_admission_gate_with_io", "yoke_runner"]
