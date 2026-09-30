"""A cold daemon start is waited out, and a stalled one names its phase.

A cold start on a loaded machine — first load of the runtime's modules and a
first Chromium exec — was measured at 12.9s. The readiness wait used to be ten
one-second polls, so it killed a live daemon mid-launch on every attempt and
reported only "state file not ready", with the daemon's phase lines discarded.
These pin that a slow but live start is waited for, that a stalled start is
stopped, reaped, and reported with the phase it reached, and that the phase
lines reach the daemon log at all.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from yoke_harness import browser_client
from yoke_harness.browser_client_readiness import (
    DAEMON_LOG_NAME,
    READINESS_POLL_SECONDS,
    READINESS_TIMEOUT_SECONDS,
    launch_daemon,
    wait_for_daemon_ready,
)


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class LiveProcess:
    pid = 4242

    def __init__(self) -> None:
        self.killed = False
        self.reaped = False

    def wait(self, timeout=None):
        if self.killed:
            self.reaped = True
            return -9
        raise subprocess.TimeoutExpired(["node"], timeout)

    def kill(self) -> None:
        self.killed = True


def _healthy_state(pid: int) -> browser_client.DaemonState:
    return browser_client.DaemonState(
        pid=pid,
        token="t",
        endpoint="http://127.0.0.1:9222",
        health="healthy",
    )


def test_a_live_daemon_slower_than_ten_seconds_is_waited_for(tmp_path) -> None:
    clock = FakeClock()
    proc = LiveProcess()
    cold_start_seconds = 12.9

    def load_state():
        return _healthy_state(proc.pid) if clock.now >= cold_start_seconds else None

    result = wait_for_daemon_ready(
        proc,
        tmp_path / DAEMON_LOG_NAME,
        load_state=load_state,
        probe_health=lambda _state: None,
        clock=clock,
        sleep=clock.sleep,
    )

    assert result == {
        "status": "started",
        "endpoint": "http://127.0.0.1:9222",
        "pid": proc.pid,
    }
    assert not proc.killed
    assert clock.now < cold_start_seconds + READINESS_POLL_SECONDS + 1e-9


def test_a_stalled_start_is_stopped_reaped_and_names_its_phase(tmp_path) -> None:
    clock = FakeClock()
    proc = LiveProcess()
    log_file = tmp_path / DAEMON_LOG_NAME
    log_file.write_text(
        "Launching Chromium (headless, throwaway profile)...\n",
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError) as exc_info:
        wait_for_daemon_ready(
            proc,
            log_file,
            load_state=lambda: None,
            probe_health=lambda _state: None,
            clock=clock,
            sleep=clock.sleep,
        )

    message = str(exc_info.value)
    assert proc.killed and proc.reaped
    assert clock.now >= READINESS_TIMEOUT_SECONDS
    assert f"pid {proc.pid}" in message
    assert "state file not written yet" in message
    assert "Launching Chromium" in message
    assert "yoke qa browser setup" in message


def test_a_daemon_that_exits_is_reported_without_waiting_out_the_budget(
    tmp_path,
) -> None:
    clock = FakeClock()
    log_file = tmp_path / DAEMON_LOG_NAME
    log_file.write_text("Error: listen EADDRINUSE 127.0.0.1:9222\n", encoding="utf-8")

    class ExitedProcess(LiveProcess):
        def wait(self, timeout=None):
            return 1

    with pytest.raises(RuntimeError, match="exited unexpectedly") as exc_info:
        wait_for_daemon_ready(
            ExitedProcess(),
            log_file,
            load_state=lambda: None,
            probe_health=lambda _state: None,
            clock=clock,
            sleep=clock.sleep,
        )

    assert "EADDRINUSE" in str(exc_info.value)
    assert "another process holds the daemon port" in str(exc_info.value)
    assert clock.now == 0.0


def test_the_daemon_log_captures_its_startup_phase_lines(tmp_path) -> None:
    log_file = tmp_path / DAEMON_LOG_NAME
    proc = launch_daemon(
        [
            sys.executable,
            "-c",
            "import sys; print('Launching Chromium...', flush=True); "
            "print('launch failed', file=sys.stderr)",
        ],
        {},
        log_file,
    )
    proc.wait(timeout=30)

    logged = log_file.read_text(encoding="utf-8")
    assert "Launching Chromium..." in logged
    assert "launch failed" in logged
