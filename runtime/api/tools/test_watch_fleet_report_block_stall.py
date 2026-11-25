"""The fleet watcher's progress-stall bound against an arriving report block."""

from __future__ import annotations

import json
from pathlib import Path

from yoke_contracts.platform_process import pid_alive
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
    monkeypatch.setenv("YOKE_WATCH_QUIET_HEARTBEAT_SECONDS", "2")
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
    """Completed passes keep a quiet fleet alive without progress wakes."""
    monkeypatch.setenv("YOKE_WATCH_PROGRESS_STALL_SECONDS", "0.3")
    # Raw probe liveness and follower progress diagnostics have separate bounds.
    monkeypatch.setenv("YOKE_WATCH_QUIET_HEARTBEAT_SECONDS", "2")
    stdout = RecordingStream()
    rc = run_probe_script(
        tmp_path,
        "import time\n"
        "time.sleep(0.4)\n"
        "for _ in range(12):\n"
        "    print('fleet pass now', flush=True)\n"
        "    time.sleep(0.05)\n",
        stdout,
    )
    assert rc == 0
    assert "no progress for" not in stdout.getvalue()
    assert "still running" not in stdout.getvalue()
    raw = (tmp_path / "raw.log").read_text()
    assert "no progress for" in raw
    assert "still running" not in raw
    assert raw.count("fleet pass ") == 12
    assert "fleet pass" not in (tmp_path / "progress.log").read_text()


def test_a_probe_blocked_inside_snapshot_read_aborts_and_is_reaped(
    tmp_path: Path, monkeypatch
) -> None:
    from yoke_core.domain import gate_stall_report, watch_runner
    from yoke_core.tools import watch_tail
    import time
    import psutil

    monkeypatch.setenv("YOKE_WATCH_PROGRESS_STALL_SECONDS", "0.5")
    monkeypatch.setattr(
        gate_stall_report, "diagnose_quiet_run",
        lambda _: gate_stall_report.StallReport(waiting_on="child process"),
    )
    identity_path = tmp_path / "child.json"
    stdout = RecordingStream()
    started: float | None = None
    drain = watch_runner.drain_watched_child

    def drain_ready_probe(**kwargs):
        nonlocal started
        # Give interpreter startup its own bound. The real drain measures
        # its quiet window from the probe's entry into the snapshot read.
        deadline = time.monotonic() + 10
        while not identity_path.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert identity_path.exists(), "probe never entered the snapshot read"
        started = time.monotonic()
        return drain(**kwargs)

    monkeypatch.setattr(watch_runner, "drain_watched_child", drain_ready_probe)
    rc = run_probe_script(
        tmp_path,
        "import json, os, pathlib, psutil, time\n"
        "from yoke_contracts.platform_process import start_identity\n"
        "process = psutil.Process()\n"
        "identity = dict(pid=process.pid, start_time=start_identity(process), "
        "parent_pid=os.getppid())\n"
        "print('probe header', flush=True)\n"
        "def read_snapshot():\n"
        f"    path = pathlib.Path({str(identity_path)!r})\n"
        "    pending = path.with_suffix('.tmp')\n"
        "    pending.write_text(json.dumps(identity), encoding='utf-8')\n"
        "    pending.replace(path)\n"
        "    time.sleep(30)\n"
        "read_snapshot()\n"
        "print('fleet pass now', flush=True)\n",
        stdout,
    )
    assert rc == watch_runner.STALL_ABORT_EXIT
    assert started is not None
    assert time.monotonic() - started < 5
    for path in ("raw.log", "progress.log"):
        text = (tmp_path / path).read_text()
        assert "aborted: fleet_probe_stalled" in text
        assert "waiting_on=child process" in text
        assert "fleet pass" not in text
    identity = json.loads(identity_path.read_text())
    assert not pid_alive(identity["pid"], identity["start_time"]), identity
    assert not psutil.pid_exists(identity["pid"]), identity
    follower = RecordingStream()
    assert watch_tail.follow(tmp_path / "progress.log", out=follower) == 0
    assert "aborted: fleet_probe_stalled" in follower.getvalue()
