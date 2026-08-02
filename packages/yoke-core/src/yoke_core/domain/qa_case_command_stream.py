"""Run one registered QA command live, capturing it whole as it goes.

A registered Command case is the final verification gate, so its single
execution has to serve two readers at once: the agent watching it happen
now, and the durable QA artifact read afterwards. Collecting the output
and revealing it only at the end serves the second reader alone — which
is why agents ran the suite by hand first, watched that run, and then
paid for the identical suite a second time through the gate.

Filtering is deliberately not repeated here. A registered command is
expected to be a watcher wrapper that already classifies its own output,
so every line it emits is relayed verbatim; re-classifying would swallow
the inner wrapper's own banners and verdict lines. What this adds is what
a bare captured subprocess cannot give an agent: a capture path announced
before the command starts, live output while it runs, and whole-group
reaping when it times out or is interrupted.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional, TextIO

#: Capture-file and banner label. Names the surface an agent is reading,
#: matching the ``watch_<kind>`` banners the wrappers already emit.
CAPTURE_KIND = "qa_case"


@dataclass(frozen=True)
class StreamedCommand:
    """One completed registered-command run and where to re-read it."""

    exit_code: int
    timed_out: bool
    output: str
    capture_path: Path


def stream_command(
    command: str,
    *,
    cwd: str,
    env: Mapping[str, str],
    timeout_seconds: Optional[float],
    stream: Optional[TextIO] = None,
) -> StreamedCommand:
    """Run *command* through a shell, relaying its output as it arrives.

    Output goes to *stream* (stderr by default) rather than stdout so the
    callers that print a JSON result — ``yoke qa case run``, plan
    execution, deployment-run execution — keep a machine-readable stdout.

    ``timeout_seconds`` of ``None`` applies no deadline here: the command
    owns its own budget (a watched pytest run starts counting after gate
    admission, not while queueing), and its own ``124`` reports the
    expiry.
    """
    # Imported here rather than at module scope: the watcher machinery
    # reaches back into this package for its scratch paths and process
    # reaping, so binding it lazily keeps that a call-time edge.
    from yoke_core.tools._watch_runner import (
        TIMEOUT_EXIT,
        mint_capture_paths,
        run_watcher,
    )
    from yoke_core.tools._watch_throttle import Classification, LineClass

    relay = Classification(LineClass.URGENT)

    def relay_every_line(_line: str) -> Classification:
        """Pass the command's own stream through without re-filtering it."""
        return relay

    raw_capture, progress_capture = mint_capture_paths(CAPTURE_KIND)
    exit_code = run_watcher(
        argv=["/bin/sh", "-c", command],
        classifier=relay_every_line,
        raw_capture=raw_capture,
        progress_capture=progress_capture,
        kind=CAPTURE_KIND,
        cwd=cwd,
        env=dict(env),
        stdout_stream=sys.stderr if stream is None else stream,
        timeout_seconds=timeout_seconds,
    )
    output = raw_capture.read_text(encoding="utf-8", errors="replace")
    # 124 is the shell's own "deadline expired" code, so a command that
    # exits 124 itself reads as a timeout — which is exactly right when
    # the command owns the budget. Either way the outcome is a failing
    # verdict with the full capture attached.
    timed_out = exit_code == TIMEOUT_EXIT
    if timed_out and timeout_seconds is not None:
        output += f"\ncommand timed out after {timeout_seconds:g} seconds\n"
    return StreamedCommand(
        exit_code=exit_code,
        timed_out=timed_out,
        output=output,
        capture_path=raw_capture,
    )


__all__ = ["CAPTURE_KIND", "StreamedCommand", "stream_command"]
