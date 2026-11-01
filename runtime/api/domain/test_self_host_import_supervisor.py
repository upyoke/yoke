"""Importer completion cannot kill the private exec bridge's container."""

from __future__ import annotations

import signal
import subprocess
import sys

import pytest


@pytest.mark.parametrize("worker_exit", (0, 7, -9))
def test_supervisor_holds_container_until_host_finishes_bridge(worker_exit):
    program = f"""
import subprocess, sys
from yoke_core.tools import self_host_import_supervisor as supervisor
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
