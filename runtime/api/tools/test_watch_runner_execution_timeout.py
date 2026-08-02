"""Execution-timeout coverage for streamed watcher children."""

from __future__ import annotations

import io
import sys
from pathlib import Path

from yoke_core.tools import _watch_runner
from yoke_core.tools._watch_throttle import Classification, LineClass


def test_watcher_timeout_reaps_the_child_after_it_starts(tmp_path: Path) -> None:
    raw_capture = tmp_path / "raw.log"
    progress_capture = tmp_path / "progress.log"

    result = _watch_runner.run_watcher(
        argv=[sys.executable, "-c", "import time; time.sleep(60)"],
        classifier=lambda _line: Classification(LineClass.NOISE),
        raw_capture=raw_capture,
        progress_capture=progress_capture,
        kind="pytest",
        stdout_stream=io.StringIO(),
        timeout_seconds=0.1,
    )

    assert result == 124
    assert "timed out after 0.1 seconds" in raw_capture.read_text()
