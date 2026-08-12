"""Regression coverage for live output from watched Python children."""

from __future__ import annotations

import io
import sys
import threading
import time
from pathlib import Path

from yoke_core.tools import _watch_runner
from yoke_core.tools._watch_throttle import Classification, LineClass


def _summary_classifier(line: str) -> Classification:
    line_class = LineClass.SUMMARY if line.startswith("MATCH") else LineClass.NOISE
    return Classification(line_class)


def test_python_output_arrives_before_the_child_exits(tmp_path: Path) -> None:
    """A plain print must cross the watcher pipe while the child is alive."""
    release = tmp_path / "release"
    script = tmp_path / "emit_then_wait.py"
    script.write_text(
        "import pathlib, time\n"
        "print('MATCH visible')\n"
        f"release = pathlib.Path({str(release)!r})\n"
        "while not release.exists():\n"
        "    time.sleep(0.02)\n",
        encoding="utf-8",
    )
    raw = tmp_path / "raw.log"
    progress = tmp_path / "progress.log"
    result: list[int] = []
    runner = threading.Thread(
        target=lambda: result.append(
            _watch_runner.run_watcher(
                argv=[sys.executable, str(script)],
                classifier=_summary_classifier,
                raw_capture=raw,
                progress_capture=progress,
                kind="unbuffered",
                stdout_stream=io.StringIO(),
            )
        )
    )

    runner.start()
    deadline = time.monotonic() + 2.0
    try:
        while time.monotonic() < deadline:
            if progress.exists() and "MATCH visible" in progress.read_text():
                break
            time.sleep(0.02)
        assert "MATCH visible" in progress.read_text(encoding="utf-8")
        assert runner.is_alive(), "output arrived only after the child exited"
    finally:
        release.touch()
        runner.join(timeout=2.0)

    assert result == [0]


def test_explicit_environment_is_copied_and_forced_unbuffered() -> None:
    source = {"PATH": "/usr/bin", "PYTHONUNBUFFERED": "0"}

    child = _watch_runner._unbuffered_child_environment(source)

    assert child == {"PATH": "/usr/bin", "PYTHONUNBUFFERED": "1"}
    assert source["PYTHONUNBUFFERED"] == "0"
