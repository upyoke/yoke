"""Auto-exiting tail follower for Yoke watcher progress captures.

Reads existing file content first, then follows the file for new
lines, exiting cleanly with code ``0`` when it observes a watcher
exit sentinel of the form ``# watch_<kind> exit=<rc>`` (the literal
footer written by :func:`yoke_core.tools._watch_runner.run_watcher`).
``<rc>`` may be negative — a signal-killed child reports the negated
signal number (e.g. ``exit=-15`` after SIGTERM).

Pure Python -- no subprocess fork -- so a Monitor running this leaves
no child ``tail`` process behind once the wrapper finishes. This is
the canonical replacement for the bare ``tail -f`` line that
``print_streaming_pair`` previously printed for the Monitor side.

CLI: ``python3 -m yoke_core.tools.watch_tail <progress-file>``.
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path
from typing import Sequence, TextIO

# Matches the wrapper-side footer format owned by
# ``_watch_runner.run_watcher`` -- single source of the literal in
# that producer; the consumer pattern lives here in lockstep. The rc
# may be negative (signal-killed child, e.g. ``exit=-15``).
EXIT_SENTINEL = re.compile(r"^# watch_\w+ exit=-?\d+")
DEFAULT_POLL_INTERVAL = 0.1


def follow(
    path: Path,
    *,
    out: TextIO | None = None,
    poll_interval: float = DEFAULT_POLL_INTERVAL,
) -> int:
    """Tail *path* until a watcher exit sentinel is observed.

    Existing content is forwarded before the follow loop begins so a
    sentinel already written before invocation is picked up. A missing
    file is tolerated -- the function waits for it to appear, then
    reads from the beginning. Returns ``0`` on sentinel observation;
    ``out`` and ``poll_interval`` are test seams.

    Self-cleaning on a closed stdout: when the reader (Claude Code's
    Monitor primitive, or any other downstream consumer) goes away, the
    next ``stream.write`` raises ``BrokenPipeError`` and the loop exits
    with code ``0``. This prevents the watch_tail-pile-up failure mode
    where a wake-loop re-arms Monitor against the same capture file and
    each invocation leaks an orphaned watch_tail subprocess because
    nothing forwards SIGTERM on Monitor close.
    """
    stream = out if out is not None else sys.stdout
    while not path.exists():
        time.sleep(poll_interval)
    with path.open("r", encoding="utf-8") as handle:
        while True:
            line = handle.readline()
            if not line:
                time.sleep(poll_interval)
                continue
            try:
                stream.write(line)
                stream.flush()
            except BrokenPipeError:
                return 0
            if EXIT_SENTINEL.match(line):
                return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="watch_tail",
        description=(
            "Auto-exiting tail follower for Yoke watcher progress "
            "captures. Forwards existing content, follows for new "
            "lines, and exits cleanly when a watcher exit sentinel "
            "(^# watch_<kind> exit=<rc>) is observed."
        ),
    )
    parser.add_argument(
        "path", type=Path, help="Progress capture file to follow."
    )
    ns = parser.parse_args(list(argv) if argv is not None else None)
    return follow(ns.path)


if __name__ == "__main__":  # pragma: no cover -- exercised via subprocess
    sys.exit(main())
