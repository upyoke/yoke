"""The fleet watcher's progress-stall bound against an arriving report block."""

from __future__ import annotations

from pathlib import Path

from yoke_core.domain.steering_fleet_report_render import REPORT_BEGIN, REPORT_END
from yoke_core.tools import watch_fleet

from runtime.api.tools.watch_fleet_test_harness import (
    RecordingStream,
    run_probe_script,
)


def test_a_stall_falling_due_mid_report_neither_tears_nor_reports(
    tmp_path: Path, monkeypatch
) -> None:
    """A block still arriving is progress in flight, not an abandoned one.

    On a quiet fleet the report interval and the progress-stall bound
    coincide, so the stall fell due on the very line that opened the
    block. Flushing it there woke the steering seat with a lone opening
    marker claiming the probe had ended before the closing marker, and
    reset the classifier so the real report never reached progress.
    """
    monkeypatch.setenv("YOKE_WATCH_PROGRESS_STALL_SECONDS", "0.2")
    stdout = RecordingStream()
    rc = run_probe_script(
        tmp_path,
        "import time\n"
        f"print({REPORT_BEGIN!r}, flush=True)\n"
        "time.sleep(0.8)\n"
        "print('composed now · 1 held scopes · hook digest')\n"
        f"print({REPORT_END!r})\n",
        stdout,
    )
    assert rc == 0
    text = stdout.getvalue()
    assert watch_fleet.PARTIAL_REPORT_NOTE.strip() not in text
    report_writes = [chunk for chunk in stdout.writes if REPORT_BEGIN in chunk]
    assert len(report_writes) == 1
    assert "hook digest" in report_writes[0]
    assert REPORT_END in report_writes[0]


def test_a_quiet_fleet_keeps_heartbeat_and_stall_diagnostics_raw(
    tmp_path: Path, monkeypatch
) -> None:
    """A fleet that deliberately emits no changes must not wake for silence."""
    monkeypatch.setenv("YOKE_WATCH_PROGRESS_STALL_SECONDS", "0.2")
    stdout = RecordingStream()
    rc = run_probe_script(
        tmp_path,
        "import time\n"
        "print('fleet item YOK-1 status idea -> implementing', flush=True)\n"
        "time.sleep(0.8)\n",
        stdout,
    )
    assert rc == 0
    assert "no progress for" not in stdout.getvalue()
    assert "still running" not in stdout.getvalue()
    raw = (tmp_path / "raw.log").read_text()
    assert "no progress for" in raw
    assert "still running" in raw
