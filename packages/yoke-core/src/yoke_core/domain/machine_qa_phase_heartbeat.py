"""Keep a plan run visibly alive through long credential-local host phases.

The plan execution's heartbeat proves to the authority that the runner still
holds the host; the printed line proves the same to whoever watches the run.
Each heartbeat does both, so a watcher never reads a normal multi-minute
operator gate, fixture cleanup, or baseline reset as a stalled run.

Blocking phases (a baseline reset is one SSH call that can take minutes) beat
from a background thread for as long as the phase runs.
"""

from __future__ import annotations

from yoke_core.domain.qa_plan_execution_checkin import communication_unknown

from collections.abc import Callable, Iterator
from contextlib import contextmanager
import json
import threading
import time

HEARTBEAT_SECONDS = 15.0
HEARTBEAT_EVENT = "machine_qa.heartbeat"


class MachineQaAborted(RuntimeError):
    """The authority requested that this runner stop and restore its host."""


def check_abort(callback):
    result = callback() if callback is not None else None
    if isinstance(result, dict) and result.get("abort_requested"):
        raise MachineQaAborted(
            "qa_host_abort_requested: stop host actions and record restore proof; "
            "retry plan abort after restoration"
        )


def emit_heartbeat_line(phase: str, elapsed_seconds: float, **detail: object) -> None:
    """Print one progress line the plan watcher counts as live progress."""
    print(
        json.dumps(
            {
                "event": HEARTBEAT_EVENT,
                "phase": phase,
                "elapsed_seconds": int(elapsed_seconds),
                **detail,
            },
            sort_keys=True,
        ),
        flush=True,
    )


@contextmanager
def heartbeat_during(
    phase: str,
    progress_callback: Callable[[], None] | None,
    *,
    interval_seconds: float = HEARTBEAT_SECONDS,
    propagate_abort: bool = True,
) -> Iterator[None]:
    """Beat every ``interval_seconds`` while the enclosed host phase runs.

    A heartbeat failure stops beating and prints the named reason. Blocking
    phases finish before cancellation or unknown delivery is raised. Cleanup
    callers suppress cancellation until restoration and proof submission finish.
    """
    stop = threading.Event()
    failures: list[Exception] = []
    started = time.monotonic()

    def beat() -> None:
        while True:
            emit_heartbeat_line(phase, time.monotonic() - started)
            if progress_callback is not None:
                try:
                    check_abort(progress_callback)
                except Exception as error:
                    failures.append(error)
                    emit_heartbeat_line(
                        phase,
                        time.monotonic() - started,
                        error_code="qa_host_abort_requested"
                        if isinstance(error, MachineQaAborted)
                        else "machine_qa_heartbeat_failed",
                        diagnostic=f"{type(error).__name__}: {error}",
                        recovery=(
                            "Keep the runner connected through cleanup and restore proof; retry yoke qa plan abort afterward."
                            if isinstance(error, MachineQaAborted)
                            else "The plan execution may lose its host lease; "
                            "check the control-plane connection, then rerun "
                            "the plan with `yoke qa plan run`."
                        ),
                    )
                    return
            if stop.wait(interval_seconds):
                return

    thread = threading.Thread(target=beat, name=f"machine-qa-{phase}", daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join()
    if failures and (
        communication_unknown(failures[0])
        or (propagate_abort and isinstance(failures[0], MachineQaAborted))
    ):
        raise failures[0]


__all__ = [
    "HEARTBEAT_EVENT",
    "HEARTBEAT_SECONDS",
    "emit_heartbeat_line",
    "heartbeat_during",
]
