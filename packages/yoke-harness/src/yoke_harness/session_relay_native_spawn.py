"""Start one detached native under supervision, on any harness.

Every harness that resumes a session by spawning a command shares this shape:
the turn outlives the relay poll that started it, so the poll cannot report
how it ended and must not block waiting. The native therefore runs under the
supervisor in its own process group, streaming its whole account into the one
per-attempt capture, and the relay reports only the safe spawn facts.

The identifier the caller passes IS the capture's name — a wake attempt id for
a resume, a launch id for a spawn — so nothing has to record where the file
went in order to find it again.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import os
import signal
import subprocess
import sys
import time
from typing import Callable, Mapping, Sequence

from yoke_contracts.session_control.resume import RESUMED_RUNNING_RESULT
from yoke_harness import session_relay_native_supervisor
from yoke_harness.session_launch_containment import record_supervised_native
from yoke_harness.session_relay_native_capture_format import utc_stamp
from yoke_harness.session_relay_native_diagnostics import (
    NativeDiagnosticError,
    cleanup_native_diagnostics,
    diagnostic_reference,
    native_diagnostic_path,
)


ProcessFactory = Callable[..., subprocess.Popen[bytes]]


@dataclass(frozen=True)
class SupervisedNative:
    """Safe spawn facts returned before the detached turn completes.

    ``pid`` names the leader of the native's process group — the supervisor
    that waits for it and records how it ended. Containing the native means
    signalling that group, so one pid still covers the whole turn.
    """

    pid: int
    binary: str
    binary_source: str
    capture_path: Path
    diagnostic_ref: str
    started_at: str
    extra_evidence: Mapping[str, str] = field(default_factory=dict)

    @property
    def evidence(self) -> dict[str, str | int]:
        return {
            "result_code": RESUMED_RUNNING_RESULT,
            "native_pid": self.pid,
            "native_binary": self.binary,
            "native_binary_source": self.binary_source,
            "native_capture_path": str(self.capture_path),
            # The reference is the only thing that maps this attempt back to
            # its capture from another seat, so it is reported on the running
            # spawn and not held back until the outcome settles.
            "native_diagnostic_ref": self.diagnostic_ref,
            "native_started_at": self.started_at,
            **self.extra_evidence,
        }


def _stop_uncontained(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except OSError:
        try:
            process.terminate()
        except OSError:
            return
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            process.kill()


def spawn_supervised_native(
    argv: Sequence[str],
    *,
    checkout: Path,
    environment: Mapping[str, str],
    attempt_id: str,
    native_session_id: str,
    binary_source: str,
    lease_id: str = "",
    extra_evidence: Mapping[str, str] | None = None,
    state_dir: Path | None = None,
    process_factory: ProcessFactory = subprocess.Popen,
    clock: Callable[[], float] = time.time,
) -> SupervisedNative | None:
    """Spawn one supervised native in its own process group and return at once."""
    now = clock()
    try:
        reference = diagnostic_reference(attempt_id)
        cleanup_native_diagnostics(state_dir, now=now)
        capture_path = native_diagnostic_path(reference, state_dir=state_dir)
    except NativeDiagnosticError:
        return None
    supervised = [
        sys.executable,
        "-m",
        session_relay_native_supervisor.__name__,
        "--capture",
        str(capture_path),
        "--",
        *(str(value) for value in argv),
    ]
    try:
        process = process_factory(
            supervised,
            cwd=checkout,
            env=dict(environment),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except (OSError, subprocess.SubprocessError):
        capture_path.unlink(missing_ok=True)
        return None
    if not record_supervised_native(
        attempt_id,
        process.pid,
        native_session_id=native_session_id,
        supervision_kind="resume",
        capture_path=capture_path,
        diagnostic_ref=reference,
        lease_id=lease_id,
        state_dir=state_dir,
        now=now,
    ):
        _stop_uncontained(process)
        capture_path.unlink(missing_ok=True)
        return None
    return SupervisedNative(
        process.pid,
        str(argv[0]),
        binary_source,
        capture_path,
        reference,
        utc_stamp(now),
        dict(extra_evidence or {}),
    )


__all__ = [
    "SupervisedNative",
    "spawn_supervised_native",
]
