"""Select-loop drain for a watched child with stall diagnosis.

Owns the quiet-period / progress-throttle / timeout wake cycle so the
shared watcher runner stays under the authored-file line cap.
"""

from __future__ import annotations

import os
import selectors
from pathlib import Path
from typing import Callable, Mapping, Optional, TextIO

from yoke_core.domain import process_group_reaping
from yoke_core.tools._watch_throttle import (
    Classification,
    LineClass,
    ProgressGate,
)
from yoke_core.tools.gate_stall_report import handle_quiet_period
from yoke_core.tools.watch_progress_stall import ProgressEmitWatch

QUIET_HEARTBEAT_SECONDS_ENV = "YOKE_WATCH_QUIET_HEARTBEAT_SECONDS"


def quiet_heartbeat_seconds(
    progress_stall_seconds: float,
    env: Mapping[str, str] | None = None,
) -> float:
    """Return the quiet-child notice cadence shared with progress stalls."""
    source = os.environ if env is None else env
    return float(source.get(QUIET_HEARTBEAT_SECONDS_ENV, str(progress_stall_seconds)))


def _route_line(
    line: str,
    *,
    now: float,
    classifier: Callable[[str], Classification],
    gate: ProgressGate,
    raw_f: TextIO,
    progress_watch: ProgressEmitWatch,
    emit_immediate: Callable[[str], None],
    emit_progress: Callable[[str, int], None],
) -> Optional[str]:
    """Record and emit one child line; return it when it is a summary.

    Shared by the live read and the post-exit drain so a line arriving in
    either place is classified, captured, and emitted identically.
    """
    raw_f.write(line)
    progress_watch.note_output(now)
    classification = classifier(line)
    cls = classification.cls
    if cls is LineClass.NOISE:
        return None
    if cls in (LineClass.URGENT, LineClass.SUMMARY, LineClass.METADATA):
        emit_immediate(line)
        return line if cls is LineClass.SUMMARY else None
    decision = gate.consider(classification)
    if decision.emit:
        progress_watch.note_progress_emit(now, classification.progress_value)
        emit_progress(line, decision.suppressed_count)
    return None


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
) -> tuple[Optional[int], Optional[str], bool]:
    """Drain *proc* stdout until exit, timeout, or nested-deadlock abort.

    Returns ``(early_exit_code, last_summary, timed_out)``. When
    *early_exit_code* is set the caller must return it immediately (abort
    footer already written). Otherwise the caller waits on *proc* unless
    *timed_out* is true.
    """
    assert proc.stdout is not None
    last_summary: Optional[str] = None
    timed_out = False
    progress_watch = ProgressEmitWatch.start(kind, now=clock())
    quiet_seconds = quiet_heartbeat_seconds(progress_watch.stall_seconds)
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
                    # An exited child is not a drained one. Its last write
                    # and its exit race the select timeout, so breaking here
                    # on the exit alone discards whatever is still in the
                    # pipe — which is exactly the terminal burst a run is
                    # read for: its verdict, its summary, its failure
                    # reason. Read what is ready, then stop.
                    while True:
                        if not selector.select(timeout=0):
                            break
                        line = proc.stdout.readline()
                        if line == "":
                            break
                        summary = _route_line(
                            line,
                            now=clock(),
                            classifier=classifier,
                            gate=gate,
                            raw_f=raw_f,
                            progress_watch=progress_watch,
                            emit_immediate=emit_immediate,
                            emit_progress=emit_progress,
                        )
                        if summary is not None:
                            last_summary = summary
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
                summary = _route_line(
                    line,
                    now=now,
                    classifier=classifier,
                    gate=gate,
                    raw_f=raw_f,
                    progress_watch=progress_watch,
                    emit_immediate=emit_immediate,
                    emit_progress=emit_progress,
                )
                if summary is not None:
                    last_summary = summary
            stall_line = progress_watch.report_if_stalled(now)
            if stall_line is not None:
                emit_immediate(stall_line)
    # Timeout stays in-band so the runner can write the normal summary +
    # exit footer; only nested-deadlock abort returns an early exit code
    # (handle_quiet_period already wrote that footer).
    return None, last_summary, timed_out


__all__ = [
    "QUIET_HEARTBEAT_SECONDS_ENV",
    "drain_watched_child",
    "quiet_heartbeat_seconds",
]
