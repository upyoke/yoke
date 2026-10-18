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
) -> Iterator[None]:
    """Beat every ``interval_seconds`` while the enclosed host phase runs.

    A heartbeat that fails stops beating and prints the named failure; the
    phase itself still finishes, because abandoning a reset or cleanup halfway
    leaves the host worse off. A failure whose delivery is unknown is raised
    once the phase completes, matching the operator gate, so the plan never
    reports the host's state as settled when the authority may disagree.
    """
    stop = threading.Event()
    failures: list[Exception] = []
    started = time.monotonic()

    def beat() -> None:
        while True:
            emit_heartbeat_line(phase, time.monotonic() - started)
            if progress_callback is not None:
                try:
                    progress_callback()
                except Exception as error:
                    failures.append(error)
                    emit_heartbeat_line(
                        phase,
                        time.monotonic() - started,
                        error_code="machine_qa_heartbeat_failed",
                        diagnostic=f"{type(error).__name__}: {error}",
                        recovery=(
                            "The plan execution may lose its host lease; "
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
    if failures and communication_unknown(failures[0]):
        raise failures[0]


__all__ = [
    "HEARTBEAT_EVENT",
    "HEARTBEAT_SECONDS",
    "emit_heartbeat_line",
    "heartbeat_during",
]
