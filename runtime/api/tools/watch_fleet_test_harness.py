"""Shared harness for driving the fleet watcher over a scripted probe.

The wrapper's contract is about what reaches the *progress* stream and in
how many writes, so the tests need a stream that records each write
separately rather than one concatenated buffer.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path


class RecordingStream:
    """Capture each write so a report's one-wake contract is observable."""

    def __init__(self) -> None:
        self.writes: list[str] = []
        self._buf = io.StringIO()

    def write(self, s: str) -> int:
        self.writes.append(s)
        return self._buf.write(s)

    def flush(self) -> None:
        self._buf.flush()

    def getvalue(self) -> str:
        return self._buf.getvalue()


def run_probe_script(tmp_path: Path, source: str, stdout: RecordingStream) -> int:
    """Run *source* as the watched probe, capturing raw and progress."""
    from yoke_core.tools import _watch_runner, watch_fleet

    script = tmp_path / "emit.py"
    script.write_text(source, encoding="utf-8")
    return _watch_runner.run_watcher(
        argv=[sys.executable, str(script)],
        classifier=watch_fleet.make_fleet_classifier(),
        raw_capture=tmp_path / "raw.log",
        progress_capture=tmp_path / "progress.log",
        kind="fleet",
        stdout_stream=stdout,
    )


__all__ = ["RecordingStream", "run_probe_script"]
