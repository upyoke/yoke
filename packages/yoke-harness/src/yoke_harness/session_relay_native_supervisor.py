"""Run one detached native to its end and leave its whole account on disk.

The relay poll that starts a native is gone long before the native finishes,
so the poll is the one process that can never say how it ended. This runs in
between: it is the leader of the native's process group, it holds both of the
native's pipes, and it holds the one handle nobody else can — the child's exit
status.

It keeps the capture current while the native runs, because two readers depend
on that: the containment sweep reads the file's modification time as the proof
that a long turn is alive rather than hung, and an operator watching a native
that has not ended yet still wants to see what it has said. The final write
adds the exit status, which is what turns a capture into a settled outcome.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import signal
import subprocess
import sys
import time
from types import FrameType
from typing import Sequence

from yoke_harness.session_relay_native_capture_format import (
    STATE_EXITED,
    STATE_RUNNING,
    compose_capture,
    utc_stamp,
)
from yoke_harness.session_relay_native_diagnostics import (
    NativeDiagnosticError,
    write_native_capture,
)
from yoke_harness.session_relay_native_streams import (
    STDERR,
    STDOUT,
    BoundedStreams,
    start_drain,
)


#: How often a running native's words reach the file. Long enough that a chatty
#: turn does not rewrite the capture on every line, short enough that the
#: containment sweep's inactivity window never mistakes output for silence.
FLUSH_INTERVAL_SECONDS = 2.0
_DRAIN_JOIN_SECONDS = 2.0
_TERMINATE_WAIT_SECONDS = 5.0


def _write(
    capture: Path,
    streams: BoundedStreams,
    *,
    state: str,
    exit_code: int | None = None,
    now: float | None = None,
) -> None:
    stdout, stderr = streams.snapshot()
    payload = compose_capture(
        stdout=stdout,
        stderr=stderr,
        state=state,
        exit_code=exit_code,
        exit_at=utc_stamp(time.time() if now is None else now)
        if state == STATE_EXITED
        else None,
    )
    try:
        write_native_capture(capture, payload)
    except NativeDiagnosticError:
        # The native's outcome matters more than its transcript: losing the
        # file must not lose the exit status the caller is waiting on.
        return


def supervise(capture: Path, native: Sequence[str]) -> int:
    """Run ``native`` to completion, keeping ``capture`` current throughout."""
    streams = BoundedStreams()
    _write(capture, streams, state=STATE_RUNNING)
    try:
        process = subprocess.Popen(
            list(native),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        streams.append(STDERR, f"native did not start: {exc}".encode())
        _write(capture, streams, state=STATE_EXITED, exit_code=None)
        return 1
    drains = tuple(
        started
        for started in (
            start_drain(process.stdout, streams, STDOUT),
            start_drain(process.stderr, streams, STDERR),
        )
        if started is not None
    )
    _install_stop_handler(process)
    while True:
        try:
            exit_code: int | None = process.wait(timeout=FLUSH_INTERVAL_SECONDS)
            break
        except subprocess.TimeoutExpired:
            if streams.take_dirty():
                _write(capture, streams, state=STATE_RUNNING)
    for drain in drains:
        drain.join(_DRAIN_JOIN_SECONDS)
    _write(capture, streams, state=STATE_EXITED, exit_code=exit_code)
    return 0


def _install_stop_handler(process: subprocess.Popen[bytes]) -> None:
    """Pass a stop signal to the native so its account is still written.

    Containment signals the whole process group, so this process is asked to
    stop at the same moment the native is. Waiting for the child rather than
    exiting immediately is what keeps the capture from being lost exactly when
    an operator most needs to read it.
    """

    def stop(_signal: int, _frame: FrameType | None) -> None:
        try:
            process.terminate()
            process.wait(timeout=_TERMINATE_WAIT_SECONDS)
        except (OSError, subprocess.SubprocessError):
            return
        except subprocess.TimeoutExpired:
            try:
                process.kill()
            except OSError:
                return

    for received in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(received, stop)
        except (OSError, ValueError):
            continue


def main(argv: Sequence[str] | None = None) -> int:
    """Supervise one native named on the command line."""
    parser = argparse.ArgumentParser(prog="yoke-native-supervisor")
    parser.add_argument("--capture", required=True)
    parser.add_argument("native", nargs=argparse.REMAINDER)
    parsed = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    native = [str(value) for value in parsed.native]
    if native and native[0] == "--":
        native = native[1:]
    capture = Path(str(parsed.capture))
    if not native:
        streams = BoundedStreams()
        streams.append(STDERR, b"supervisor was given no native to run")
        _write(capture, streams, state=STATE_EXITED, exit_code=None)
        return 2
    return supervise(capture, native)


if __name__ == "__main__":  # pragma: no cover - process entrypoint
    raise SystemExit(main())


__all__ = ["FLUSH_INTERVAL_SECONDS", "main", "supervise"]
