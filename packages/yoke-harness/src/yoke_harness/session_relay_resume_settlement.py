"""Collect finished detached resumes and settle each attempt that started one.

A detached resume is reported the moment it spawns, because the turn it runs
outlives the relay poll that started it. That first report is deliberately
non-terminal, and for a while nothing ever replaced it: a native that refused
in its first second looked exactly like one still reasoning, until the control
plane inferred an outcome from twenty minutes of session silence. The exit
status had been sitting on the machine that started it the whole time.

The supervisor beside each resume records that exit status, and this module
turns it into the terminal report the attempt has been waiting for.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
from typing import Any, Callable

from yoke_contracts.session_control.resume import (
    RESUME_EXITED_NONZERO_RESULT,
    RESUMED_COMPLETED_RESULT,
    RESUMED_DIED_RESULT,
)
from yoke_harness.session_launch_containment import (
    SupervisedResume,
    release_supervised_native,
    supervised_resumes,
)
from yoke_harness.session_relay_diagnostic_retention import retain_private_diagnostic
from yoke_harness.session_relay_native_diagnostics import classify_native_failure
from yoke_harness.session_relay_report_delivery import deliver_terminal_report
from yoke_harness.session_relay_resume_watch import (
    read_resume_outcome,
    resume_outcome_path,
)
from yoke_harness.session_relay_runtime import (
    RelayAdapterResult,
    RelayPrivateDiagnostic,
)


CAPTURE_TAIL_BYTES = 32 * 1024
Dispatcher = Callable[..., Any]


@dataclass(frozen=True)
class FinishedNativeResume:
    """One resume whose process is over, and the report that settles it."""

    attempt_id: str
    lease_id: str
    result: RelayAdapterResult
    outcome_path: Path | None


def _capture_tail(path: Path | None) -> bytes:
    if path is None:
        return b""
    try:
        with path.open("rb") as stream:
            stream.seek(0, os.SEEK_END)
            stream.seek(max(0, stream.tell() - CAPTURE_TAIL_BYTES), os.SEEK_SET)
            return stream.read(CAPTURE_TAIL_BYTES)
    except OSError:
        return b""


def _result(exit_code: int | None, tail: bytes) -> RelayAdapterResult:
    if exit_code == 0:
        return RelayAdapterResult(
            RESUMED_COMPLETED_RESULT,
            evidence={"exit_code": 0, "result_code": RESUMED_COMPLETED_RESULT},
        )
    code = RESUMED_DIED_RESULT if exit_code is None else RESUME_EXITED_NONZERO_RESULT
    evidence: dict[str, Any] = {"result_code": code}
    if exit_code is not None:
        evidence["exit_code"] = exit_code
    # The tail is the only account of why the native refused, so it is retained
    # by the same machine-local diagnostic store every other native failure
    # uses: the report carries its opaque reference, never its text.
    return RelayAdapterResult(
        code,
        evidence=evidence,
        private_diagnostic=RelayPrivateDiagnostic(
            classify_native_failure(tail),
            error_step="resume",
            stdout=tail,
        ),
    )


def _finished(record: SupervisedResume) -> FinishedNativeResume | None:
    if not record.attempt_id or not record.lease_id:
        return None
    capture = record.capture_path
    outcome_path = None if capture is None else resume_outcome_path(capture)
    settled, exit_code = read_resume_outcome(outcome_path)
    if not settled:
        if record.running:
            return None
        # The process is gone without leaving an outcome: its supervisor was
        # killed alongside it, or never got far enough to write one.
        exit_code = None
    return FinishedNativeResume(
        record.attempt_id,
        record.lease_id,
        _result(exit_code, _capture_tail(capture)),
        outcome_path,
    )


def finished_native_resumes(
    *,
    state_dir: Path | None = None,
) -> tuple[FinishedNativeResume, ...]:
    """Return every supervised resume whose process has finished running."""
    records = supervised_resumes(state_dir=state_dir)
    finished = (_finished(record) for record in records)
    return tuple(record for record in finished if record is not None)


def _release(finished: FinishedNativeResume, *, state_dir: Path | None) -> None:
    release_supervised_native(finished.attempt_id, state_dir=state_dir)
    if finished.outcome_path is None:
        return
    try:
        finished.outcome_path.unlink(missing_ok=True)
    except OSError:
        return


def settle_finished_native_resumes(
    dispatcher: Dispatcher,
    function_id: str,
    *,
    relay_id: str,
    machine_id: str,
    state_dir: Path | None,
    timeout_s: int,
) -> tuple[str, ...]:
    """Report every finished resume and return the attempts settled here."""
    settled: list[str] = []
    for finished in finished_native_resumes(state_dir=state_dir):
        result = retain_private_diagnostic(
            finished.result,
            state_dir=state_dir,
            relay_id=relay_id,
            machine_id=machine_id,
        )
        report = deliver_terminal_report(
            dispatcher,
            function_id,
            {
                "relay_id": relay_id,
                "job_kind": "wake",
                "job_id": finished.attempt_id,
                "lease_id": finished.lease_id,
                "result": result.result_code,
                "evidence": dict(result.evidence),
            },
            state_dir=state_dir,
            timeout_s=timeout_s,
        )
        if not getattr(report, "success", False):
            # The record stays, so the next poll reports this outcome again.
            continue
        _release(finished, state_dir=state_dir)
        settled.append(finished.attempt_id)
    return tuple(settled)


__all__ = [
    "CAPTURE_TAIL_BYTES",
    "FinishedNativeResume",
    "finished_native_resumes",
    "settle_finished_native_resumes",
]
