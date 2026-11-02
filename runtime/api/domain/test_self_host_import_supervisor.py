"""Importer completion cannot kill the private exec bridge's container."""

from __future__ import annotations

import signal
import subprocess
import sys

import pytest


@pytest.mark.parametrize("worker_exit", (0, 7, -9))
@pytest.mark.parametrize("signal_timing", ("host", "wait-lock"))
def test_supervisor_holds_container_until_host_finishes_bridge(
    worker_exit, signal_timing
):
    program = f"""
import signal, subprocess, sys, threading, time
from yoke_core.tools import self_host_import_supervisor as supervisor
if {signal_timing!r} == "wait-lock":
    original_wait = threading.Condition.wait
    def wait_with_signal(condition, timeout=None):
        assert condition._is_owned()
        signal.raise_signal(signal.SIGUSR1)
        return original_wait(condition, timeout)
    threading.Condition.wait = wait_with_signal
    def sleep_with_signal(seconds):
        condition = threading.Condition(threading.Lock())
        with condition:
            assert condition._is_owned()
            signal.raise_signal(signal.SIGUSR1)
    time.sleep = sleep_with_signal
original = subprocess.Popen
worker = ({worker_exit!r})
script = ("import os, signal; os.kill(os.getpid(), signal.SIGKILL)"
          if worker < 0 else "raise SystemExit(" + str(worker) + ")")
class Child:
    def __init__(self):
        self.process = original([sys.executable, "-c", script])
    def wait(self):
        result = self.process.wait()
        print("worker_finished", flush=True)
        return result
    def poll(self):
        return self.process.poll()
    def kill(self):
        self.process.kill()
supervisor.subprocess.Popen = lambda *args, **kwargs: Child()
supervisor.os.geteuid = lambda: 1000
raise SystemExit(supervisor.main(["--import-universe"]))
"""
    process = subprocess.Popen(
        [sys.executable, "-c", program],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout.readline().strip() == "worker_finished"
        if signal_timing == "host":
            assert process.poll() is None
            process.send_signal(signal.SIGUSR1)
        _, error = process.communicate(timeout=10)
        assert process.returncode == (
            128 - worker_exit if worker_exit < 0 else worker_exit
        ), error
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate()


def test_supervisor_bounds_unconfirmed_bridge_wait(monkeypatch, capsys):
    from yoke_core.tools import self_host_import_supervisor as supervisor

    class Child:
        def wait(self):
            return 0

        def poll(self):
            return 0

    times = iter((0, supervisor.HANDOFF_TIMEOUT_SECONDS + 1))
    previous = signal.getsignal(signal.SIGUSR1)
    monkeypatch.setattr(supervisor.subprocess, "Popen", lambda *args: Child())
    monkeypatch.setattr(supervisor.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(supervisor.time, "monotonic", lambda: next(times))
    assert supervisor.main(["--import-universe"]) == 1
    assert "self_host_import_bridge_unconfirmed" in capsys.readouterr().err
    assert signal.getsignal(signal.SIGUSR1) == previous


def test_supervisor_kills_running_child_after_failure(monkeypatch, capsys):
    from yoke_core.tools import self_host_import_supervisor as supervisor

    class Child:
        killed = False

        def wait(self):
            if not self.killed:
                raise RuntimeError("worker wait failed")
            return -9

        def poll(self):
            return None

        def kill(self):
            self.killed = True

    child = Child()
    monkeypatch.setattr(supervisor.subprocess, "Popen", lambda *args: child)
    monkeypatch.setattr(supervisor.os, "geteuid", lambda: 1000)
    assert supervisor.main(["--import-universe"]) == 1
    assert child.killed
    assert "self_host_import_supervisor_failed" in capsys.readouterr().err
