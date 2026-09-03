"""Collect finished detached resumes and settle each attempt that started one.

A detached resume is reported the moment it spawns, because the turn it runs
outlives the relay poll that started it. That first report is deliberately
non-terminal, and for a while nothing ever replaced it: a native that refused
in its first second looked exactly like one still reasoning, until the control
plane inferred an outcome from twenty minutes of session silence. The exit
status had been sitting on the machine that started it the whole time.

The supervisor running each resume writes that exit status into the same
capture the native's own words go to, and this module turns it into the
terminal report the attempt has been waiting for. It is harness-agnostic on
purpose: every supervised resume is settled here, because the supervisor that
wrote the capture is the same one on every harness.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from yoke_contracts.session_control.resume import (
    RESUME_EXITED_NONZERO_RESULT,
    RESUMED_COMPLETED_RESULT,
    RESUMED_DIED_RESULT,
)
from yoke_contracts.process_ancestry import process_start_time
from yoke_harness.session_launch_containment import (
    release_supervised_native,
    supervised_records,
)
from yoke_harness.session_relay_native_capture_format import NativeCapture
from yoke_harness.session_relay_native_diagnostics import (
    classify_native_failure,
    read_native_capture,
)
from yoke_harness.session_relay_report_delivery import deliver_terminal_report
from yoke_harness.session_relay_runtime import RelayAdapterResult


Dispatcher = Callable[..., Any]


@dataclass(frozen=True)
class SupervisedResume:
    """One detached resume this machine started, and whether it still runs."""

    attempt_id: str
    pid: int
    lease_id: str
    capture_path: Path | None
    diagnostic_ref: str | None
    running: bool


@dataclass(frozen=True)
class FinishedNativeResume:
    """One resume whose process is over, and the report that settles it."""

    attempt_id: str
    lease_id: str
    result: RelayAdapterResult


def _result(
    capture: NativeCapture | None,
    diagnostic_ref: str | None,
) -> RelayAdapterResult:
    """Turn one finished native's own account into this attempt's outcome."""
    exit_code = capture.exit_code if capture is not None else None
    if capture is not None and exit_code == 0:
        return RelayAdapterResult(
            RESUMED_COMPLETED_RESULT,
            evidence={"exit_code": 0, "result_code": RESUMED_COMPLETED_RESULT},
        )
    code = RESUMED_DIED_RESULT if exit_code is None else RESUME_EXITED_NONZERO_RESULT
    evidence: dict[str, Any] = {"result_code": code}
    if exit_code is not None:
        evidence["exit_code"] = exit_code
    if capture is None:
        return RelayAdapterResult(code, evidence=evidence)
    if capture.exit_at:
        evidence["native_exit_at"] = capture.exit_at
    # The capture is already retained under this attempt's own name, so the
    # report carries that reference and the one line the native ended on —
    # never the streams themselves.
    if diagnostic_ref:
        evidence["native_diagnostic_ref"] = diagnostic_ref
    tail = capture.tail
    if tail:
        evidence["native_stderr_tail"] = tail
        evidence["native_error_class"] = classify_native_failure(capture.stderr)
    return RelayAdapterResult(code, evidence=evidence)


def _finished(record: SupervisedResume) -> FinishedNativeResume | None:
    if not record.attempt_id or not record.lease_id:
        return None
    capture = read_native_capture(record.capture_path)
    settled = capture is not None and capture.exited
    if not settled and record.running:
        return None
    # The process is gone without a settled capture: its supervisor was killed
    # alongside it, or never got far enough to record how the native ended.
    return FinishedNativeResume(
        record.attempt_id,
        record.lease_id,
        _result(capture if settled else None, record.diagnostic_ref),
    )


def supervised_resumes(state_dir: Path | None = None) -> tuple[SupervisedResume, ...]:
    """Project the machine's supervision records onto the resumes among them."""
    resumes: list[SupervisedResume] = []
    for _path, payload in supervised_records(state_dir):
        if str(payload.get("supervision_kind") or "") != "resume":
            continue
        pid = payload.get("pid")
        if not isinstance(pid, int) or pid <= 0:
            continue
        capture = payload.get("capture_path")
        reference = payload.get("diagnostic_ref")
        resumes.append(
            SupervisedResume(
                attempt_id=str(payload.get("launch_id") or ""),
                pid=pid,
                lease_id=str(payload.get("lease_id") or ""),
                capture_path=Path(capture) if isinstance(capture, str) else None,
                diagnostic_ref=reference if isinstance(reference, str) else None,
                # A reused pid names a different process, so the resume this
                # record was written for is gone either way.
                running=process_start_time(pid) == payload.get("process_start_time"),
            )
        )
    return tuple(resumes)


def finished_native_resumes(
    *,
    state_dir: Path | None = None,
) -> tuple[FinishedNativeResume, ...]:
    """Return every supervised resume whose process has finished running."""
    finished = (_finished(record) for record in supervised_resumes(state_dir))
    return tuple(record for record in finished if record is not None)


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
        report = deliver_terminal_report(
            dispatcher,
            function_id,
            {
                "relay_id": relay_id,
                "job_kind": "wake",
                "job_id": finished.attempt_id,
                "lease_id": finished.lease_id,
                "result": finished.result.result_code,
                "evidence": {
                    **dict(finished.result.evidence),
                    "relay_id": relay_id,
                    "machine_id": machine_id,
                },
            },
            state_dir=state_dir,
            timeout_s=timeout_s,
        )
        if not getattr(report, "success", False):
            # The record stays, so the next poll reports this outcome again.
            continue
        release_supervised_native(finished.attempt_id, state_dir=state_dir)
        settled.append(finished.attempt_id)
    return tuple(settled)


__all__ = [
    "FinishedNativeResume",
    "SupervisedResume",
    "finished_native_resumes",
    "settle_finished_native_resumes",
    "supervised_resumes",
]
