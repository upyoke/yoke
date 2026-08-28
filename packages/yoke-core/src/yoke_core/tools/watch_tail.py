"""Auto-exiting tail follower for Yoke watcher progress captures.

Reads existing file content first, then follows the file for new
lines, exiting cleanly with code ``0`` when it observes a watcher
exit sentinel of the form ``# watch_<kind> exit=<rc>`` (the literal
footer written by :func:`yoke_core.tools._watch_runner.run_watcher`).
``<rc>`` may be negative — a signal-killed child reports the negated
signal number (e.g. ``exit=-15`` after SIGTERM).

Following is bounded by writer evidence, not only by that sentinel. A
bound watcher stamps its pid into the capture's first line (see
:mod:`yoke_core.tools._watch_capture_binding`), so a capture that no
process ever claimed, and a capture whose claiming process died before
its sentinel, both end in a named non-zero refusal instead of an
unbounded silent wait.

Pure Python -- no subprocess fork -- so a Monitor running this leaves
no child ``tail`` process behind once the wrapper finishes. This is
the canonical replacement for the bare ``tail -f`` line that
``print_streaming_pair`` previously printed for the Monitor side.

CLI: ``yoke watch tail <progress-file>``. The module invocation
(``python3 -m yoke_core.tools.watch_tail``) remains the operator-debug
fallback.
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path
from typing import Callable, Sequence, TextIO

from yoke_core.tools._watch_capture_binding import (
    DEFAULT_WRITER_GRACE_SECONDS,
    UNWRITTEN_CAPTURE_EXIT,
    dead_writer_refusal,
    unwritten_capture_refusal,
    writer_alive,
    writer_pid,
)

# Matches the wrapper-side footer format owned by
# ``_watch_runner.run_watcher`` -- single source of the literal in
# that producer; the consumer pattern lives here in lockstep. The rc
# may be negative (signal-killed child, e.g. ``exit=-15``).
WRAPPER_MODULE = "yoke_core.tools.watch_tail"
EXIT_SENTINEL = re.compile(r"^# watch_\w+ exit=-?\d+")
DEFAULT_POLL_INTERVAL = 0.1
# argparse prog for a direct module invocation; the CLI adapter passes the
# ``yoke watch tail`` form so help reads back the command as typed.
DEFAULT_PROG = "watch_tail"


def _refuse(stream: TextIO, message: str) -> int:
    """Emit *message* on the followed stream and return the refusal code.

    The refusal goes where the tail's own content goes, because that is
    the stream a follower's reader is watching; a diagnosis nobody reads
    is the same silence this refusal exists to end.
    """
    try:
        stream.write(message)
        stream.flush()
    except BrokenPipeError:
        return 0
    return UNWRITTEN_CAPTURE_EXIT


def _forward_remaining(handle: TextIO, stream: TextIO) -> int | None:
    """Forward everything left in *handle*; return ``0`` on a sentinel."""
    for line in handle:
        try:
            stream.write(line)
            stream.flush()
        except BrokenPipeError:
            return 0
        if EXIT_SENTINEL.match(line):
            return 0
    return None


def follow(
    path: Path,
    *,
    out: TextIO | None = None,
    poll_interval: float = DEFAULT_POLL_INTERVAL,
    grace_seconds: float = DEFAULT_WRITER_GRACE_SECONDS,
    clock: Callable[[], float] = time.monotonic,
) -> int:
    """Tail *path* until a watcher exit sentinel or a diagnosed refusal.

    Existing content is forwarded before the follow loop begins so a
    sentinel already written before invocation is picked up. A missing
    file is tolerated -- the function waits for it to appear, then
    reads from the beginning. Returns ``0`` on sentinel observation;
    ``out``, ``poll_interval``, ``grace_seconds`` and ``clock`` are test
    seams.

    Waiting is bounded by writer evidence. A bound watcher claims its
    progress capture with a pid marker before it runs anything (see
    :mod:`yoke_core.tools._watch_capture_binding`), so a capture that is
    still empty and unclaimed once ``grace_seconds`` has passed is one
    no run will ever write, and a claimed capture whose writer is gone
    without a sentinel will never gain one. Both return
    ``UNWRITTEN_CAPTURE_EXIT`` with the cause and the recovery step
    rather than waiting forever. A run that is merely slow to start --
    queued behind an admission gate, say -- has already stamped its
    marker, so the grace window never cuts one short.

    Self-cleaning on a closed stdout: when the reader (Claude Code's
    Monitor primitive, or any other downstream consumer) goes away, the
    next ``stream.write`` raises ``BrokenPipeError`` and the loop exits
    with code ``0``. This prevents the watch_tail-pile-up failure mode
    where a wake-loop re-arms Monitor against the same capture file and
    each invocation leaks an orphaned watch_tail subprocess because
    nothing forwards SIGTERM on Monitor close.
    """
    stream = out if out is not None else sys.stdout
    deadline = clock() + grace_seconds
    while not path.exists():
        if clock() >= deadline:
            return _refuse(
                stream,
                unwritten_capture_refusal(path, grace_seconds=grace_seconds),
            )
        time.sleep(poll_interval)
    with path.open("r", encoding="utf-8") as handle:
        owner: int | None = None
        while True:
            line = handle.readline()
            if not line:
                if owner is None:
                    if clock() >= deadline and path.stat().st_size == 0:
                        return _refuse(
                            stream,
                            unwritten_capture_refusal(
                                path, grace_seconds=grace_seconds
                            ),
                        )
                elif not writer_alive(owner):
                    # Liveness is read before the final drain, so a
                    # sentinel written in the instant before the writer
                    # exited is still forwarded rather than refused.
                    drained = _forward_remaining(handle, stream)
                    if drained is not None:
                        return drained
                    return _refuse(stream, dead_writer_refusal(path, pid=owner))
                time.sleep(poll_interval)
                continue
            try:
                stream.write(line)
                stream.flush()
            except BrokenPipeError:
                return 0
            if owner is None:
                owner = writer_pid(line)
            if EXIT_SENTINEL.match(line):
                return 0


def main(argv: Sequence[str] | None = None, *, prog: str = DEFAULT_PROG) -> int:
    parser = argparse.ArgumentParser(
        prog=prog,
        description=(
            "Auto-exiting tail follower for Yoke watcher progress "
            "captures. Forwards existing content, follows for new "
            "lines, and exits cleanly when a watcher exit sentinel "
            "(^# watch_<kind> exit=<rc>) is observed. Exits "
            f"{UNWRITTEN_CAPTURE_EXIT} instead of waiting forever when the "
            "capture has no writer: a wrapper claims its progress "
            "capture with a '# watch_<kind> writer_pid=<pid>' first "
            "line, so a capture still empty and unclaimed after "
            f"{DEFAULT_WRITER_GRACE_SECONDS:g}s was never the one the run "
            "wrote to (paste the --print-streaming-pair background "
            "command verbatim -- its --raw-capture/--progress-capture "
            "flags bind the run to this tail), and a claimed capture "
            "whose writer died without a sentinel will never gain one."
        ),
    )
    parser.add_argument(
        "path", type=Path, help="Progress capture file to follow."
    )
    ns = parser.parse_args(list(argv) if argv is not None else None)
    return follow(ns.path)


if __name__ == "__main__":  # pragma: no cover -- exercised via subprocess
    sys.exit(main())
