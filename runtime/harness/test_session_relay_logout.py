"""Real TERM must bound relay interpreter exit, including blocked workers and IO."""

import os
import signal
import subprocess
import sys
import time

import pytest


@pytest.mark.parametrize(
    "blocked", ["idle", "poll", "maintenance", "settlement", "refresh", "report"]
)
def test_term_exits_below_user_manager_budget_and_keeps_custody(tmp_path, blocked):
    ready = tmp_path / "ready"
    custody = tmp_path / "native-custody.json"
    program = """
import sys, time
from pathlib import Path
from types import SimpleNamespace
from yoke_harness.session_relay_daemon import serve_forever
from yoke_harness.session_relay_supervision import refreshing_inventory
root, blocked = Path(sys.argv[1]), sys.argv[2]
def hold():
    (root / 'native-custody.json').write_text('durable-attempt')
    (root / 'ready').touch()
    time.sleep(60)
def cycle(**kwargs):
    if blocked == 'poll': hold()
    if blocked == 'settlement': kwargs['dispatch_job'](hold)
    if blocked == 'report':
        from yoke_harness.session_relay_report_delivery import deliver_terminal_report
        def report():
            deliver_terminal_report(lambda **kw: hold(), 'unused',
                dict(relay_id='relay',machine_id='machine',job_kind='launch',
                     job_id='job',lease_id='lease',result='native_created'),
                state_dir=root, timeout_s=10)
        kwargs['dispatch_job'](report)
    if blocked == 'refresh':
        with refreshing_inventory(hold): time.sleep(60)
    if blocked == 'idle': (root / 'ready').touch()
    return SimpleNamespace(state='active')
serve_forever(state_dir=root, cycle=cycle,
              cycle_maintenance=hold if blocked == 'maintenance' else None)
print('stopped', flush=True)
"""
    process = subprocess.Popen(
        [sys.executable, "-c", program, str(tmp_path), blocked],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 10
        while (
            not ready.exists()
            and process.poll() is None
            and time.monotonic() < deadline
        ):
            time.sleep(0.02)
        assert ready.exists(), process.communicate(timeout=1)
        started = time.monotonic()
        os.kill(process.pid, signal.SIGTERM)
        out, err = process.communicate(timeout=4)
        assert process.returncode == 0, err
        assert "stopped" in out
        assert time.monotonic() - started < 4
        if blocked != "idle":
            assert custody.read_text() == "durable-attempt"
        if blocked == "report":
            import json
            from yoke_harness.session_relay_report_delivery import (
                PENDING_REPORT_DIR_NAME,
            )

            pending = list((tmp_path / PENDING_REPORT_DIR_NAME).glob("*.json"))
            assert len(pending) == 1
            assert json.loads(pending[0].read_text())["result"] == "native_created"
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=2)


def test_stop_closes_admission_and_cancels_queued_jobs(tmp_path):
    import threading
    from yoke_harness.session_relay_daemon import _StopRequest
    from yoke_harness.session_relay_failure_log import FailureReporter
    from yoke_harness.session_relay_supervision import Supervisor

    stop = _StopRequest()
    supervisor = Supervisor(1, FailureReporter(state_dir=tmp_path), stop)
    entered, release = threading.Event(), threading.Event()
    calls = []

    def active():
        entered.set()
        release.wait(5)

    supervisor.dispatch(active)
    assert entered.wait(1)
    supervisor.dispatch(lambda: calls.append("queued"))
    stop.set("signal:SIGTERM")
    supervisor.dispatch(lambda: calls.append("new"))
    supervisor.pool.shutdown(wait=False, cancel_futures=True)
    release.set()
    supervisor.drain(timeout=1)
    assert calls == []


def test_ordinary_poll_failure_settles_refresh_before_another_cycle():
    import threading
    from yoke_harness.session_relay_supervision import refreshing_inventory

    entered, finished = threading.Event(), threading.Event()

    def refresh():
        entered.set()
        time.sleep(0.05)
        finished.set()

    with pytest.raises(RuntimeError, match="poll failed"):
        with refreshing_inventory(refresh):
            assert entered.wait(1)
            raise RuntimeError("poll failed")
    assert finished.is_set()
