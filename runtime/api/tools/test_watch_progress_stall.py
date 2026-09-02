"""Progress-throttle stall reports for watched runs."""

from __future__ import annotations

import io
import sys
from pathlib import Path

from yoke_core.tools import _watch_runner, watch_progress_stall
from yoke_core.tools._watch_throttle import Classification, LineClass, ThrottlePolicy


def test_progress_stall_seconds_refuses_non_positive(monkeypatch):
    monkeypatch.setenv(watch_progress_stall.PROGRESS_STALL_SECONDS_ENV, "0")
    try:
        watch_progress_stall.progress_stall_seconds()
        assert False, "expected ValueError"
    except ValueError as exc:
        assert watch_progress_stall.PROGRESS_STALL_SECONDS_ENV in str(exc)


def test_progress_emit_watch_names_throttle_mirage():
    watch = watch_progress_stall.ProgressEmitWatch.start("pytest", now=0.0)
    cadence = watch.stall_seconds
    watch.note_progress_emit(0.0, 90.0)
    watch.note_output(cadence - 10.0)
    line = watch.report_if_stalled(cadence)
    assert line is not None
    assert f"no progress for {cadence:g}s" in line
    assert "last reported 90%" in line
    assert "waiting_on=progress_throttle" in line
    assert "child output 10s ago" in line
    # Cadence: do not re-report until another stall interval elapses.
    assert watch.report_if_stalled(cadence + 30.0) is None


def test_watcher_reports_progress_throttle_while_child_keeps_printing(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setenv(watch_progress_stall.PROGRESS_STALL_SECONDS_ENV, "0.05")
    monkeypatch.setenv(_watch_runner.QUIET_HEARTBEAT_SECONDS_ENV, "30")

    script = tmp_path / "emit.py"
    script.write_text(
        "\n".join(
            [
                "import sys, time",
                "print('[ 90%]', flush=True)",
                "for _ in range(40):",
                "    print('.' * 8, flush=True)",
                "    time.sleep(0.02)",
                "print('[100%]', flush=True)",
                "sys.exit(0)",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    def classify(line: str) -> Classification:
        if "%" in line:
            # Extract the numeric percent for throttle + stall watch.
            digits = "".join(ch for ch in line if ch.isdigit() or ch == ".")
            value = float(digits) if digits else None
            return Classification(LineClass.PROGRESS, progress_value=value)
        return Classification(LineClass.NOISE)

    out = io.StringIO()
    raw = tmp_path / "raw.log"
    progress = tmp_path / "progress.log"
    rc = _watch_runner.run_watcher(
        argv=[sys.executable, str(script)],
        classifier=classify,
        raw_capture=raw,
        progress_capture=progress,
        kind="pytest",
        stdout_stream=out,
        # Large percent step so 90% is the only emit until 100%.
        policy=ThrottlePolicy(percent_step=50.0),
    )
    assert rc == 0
    text = progress.read_text(encoding="utf-8")
    assert "waiting_on=progress_throttle" in text
    assert "last reported 90%" in text
