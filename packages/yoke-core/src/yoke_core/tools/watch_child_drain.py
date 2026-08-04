"""Select-loop drain for a watched child with stall diagnosis.

Owns the quiet-period / progress-throttle / timeout wake cycle so the
shared watcher runner stays under the authored-file line cap.
"""

from __future__ import annotations

import os
import selectors
from pathlib import Path
from typing import Callable, Optional, TextIO

from yoke_core.domain import process_group_reaping
from yoke_core.tools._watch_throttle import (
    Classification,
    LineClass,
    ProgressGate,
)
from yoke_core.tools.gate_stall_report import handle_quiet_period
from yoke_core.tools.watch_progress_stall import ProgressEmitWatch

QUIET_HEARTBEAT_SECONDS_ENV = "YOKE_WATCH_QUIET_HEARTBEAT_SECONDS"


def drain_watched_child(
    *,
    proc,
    kind: str,
    classifier: Callable[[str], Classification],
    gate: ProgressGate,
    raw_f: TextIO,
    progress_f: TextIO,
    out: TextIO,
    emit_immediate: Callable[[str], None],
    emit_progress: Callable[[str, int], None],
    pump_tick: Callable[[], None],
    clock: Callable[[], float],
    deadline: float | None,
    timeout_seconds: float | None,
    raw_capture: Path,
    stall_abort_exit: int,
    timeout_exit: int,
) -> tuple[Optional[int], Optional[str], bool]:
    """Drain *proc* stdout until exit, timeout, or nested-deadlock abort.

    Returns ``(early_exit_code, last_summary, timed_out)``. When
    *early_exit_code* is set the caller must return it immediately (abort
    footer already written). Otherwise the caller waits on *proc* unless
    *timed_out* is true, in which case it uses *timeout_exit*.
    """
    assert proc.stdout is not None
    last_summary: Optional[str] = None
    timed_out = False
    quiet_seconds = float(os.environ.get(QUIET_HEARTBEAT_SECONDS_ENV, "60"))
    progress_watch = ProgressEmitWatch.start(kind, now=clock())
    with selectors.DefaultSelector() as selector:
        selector.register(proc.stdout, selectors.EVENT_READ)
        while True:
            now = clock()
            wait_seconds = progress_watch.next_wait_seconds(
                now, quiet_seconds=quiet_seconds, deadline=deadline
            )
            events = selector.select(timeout=wait_seconds)
            pump_tick()
            now = clock()
            if not events:
                if proc.poll() is not None:
                    break
                if deadline is not None and now >= deadline:
                    process_group_reaping.terminate_process_group(proc)
                    timed_out = True
                    timeout_line = (
                        f"# watch_{kind} timed out after "
                        f"{timeout_seconds:g} seconds; "
                        "child process group reaped\n"
                    )
                    raw_f.write(timeout_line)
                    emit_immediate(timeout_line)
                    break
                abort_exit = handle_quiet_period(
                    root_pid=proc.pid,
                    kind=kind,
                    quiet_seconds=quiet_seconds,
                    emit_immediate=emit_immediate,
                    write_raw=raw_f.write,
                    terminate_child=lambda: (
                        process_group_reaping.terminate_process_group(proc)
                    ),
                    raw_capture=raw_capture,
                    stall_abort_exit=stall_abort_exit,
                )
                if abort_exit is not None:
                    return abort_exit, last_summary, False
            else:
                line = proc.stdout.readline()
                if line == "":
                    if proc.poll() is not None:
                        break
                    continue
                raw_f.write(line)
                progress_watch.note_output(now)
                classification = classifier(line)
                cls = classification.cls
                if cls is LineClass.NOISE:
                    pass
                elif cls in (
                    LineClass.URGENT,
                    LineClass.SUMMARY,
                    LineClass.METADATA,
                ):
                    emit_immediate(line)
                    if cls is LineClass.SUMMARY:
                        last_summary = line
                else:
                    decision = gate.consider(classification)
                    if decision.emit:
                        progress_watch.note_progress_emit(
                            now, classification.progress_value
                        )
                        emit_progress(line, decision.suppressed_count)
            stall_line = progress_watch.report_if_stalled(now)
            if stall_line is not None:
                emit_immediate(stall_line)
    if timed_out:
        return timeout_exit, last_summary, True
    return None, last_summary, False


__all__ = [
    "QUIET_HEARTBEAT_SECONDS_ENV",
    "drain_watched_child",
]
