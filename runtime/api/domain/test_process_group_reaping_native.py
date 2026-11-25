"""The legacy watcher API retains native process custody through root exit."""

import subprocess
import sys
import time
from types import SimpleNamespace
from unittest.mock import Mock

import psutil
import pytest

from yoke_contracts import platform_process, terminal_detached_process

from yoke_core.domain import process_group_reaping as reaping


def test_native_spawn_returns_process_with_custody_and_forwards_io(monkeypatch):
    process = Mock(spec=subprocess.Popen)
    handle = SimpleNamespace(process=process)
    spawn = Mock(return_value=handle)
    monkeypatch.setattr(reaping, "spawn_group", spawn)
    result = reaping.popen_in_process_group(
        ["child", "two words"], stdout=subprocess.PIPE,
    )
    assert result is process
    assert result._yoke_process_group is handle
    spawn.assert_called_once_with(["child", "two words"], stdout=subprocess.PIPE)


@pytest.mark.parametrize("failure", [None, PermissionError("survivor refused stop")])
def test_native_stop_keeps_custody_after_leader_exit(monkeypatch, failure):
    process = Mock(spec=subprocess.Popen)
    process.poll.return_value = 0
    process._yoke_process_group = handle = object()
    stop = Mock(side_effect=failure)
    monkeypatch.setattr(reaping, "stop_group", stop)
    if failure:
        with pytest.raises(PermissionError, match="survivor refused stop"):
            reaping.terminate_process_group(process, grace_seconds=2)
    else:
        reaping.terminate_process_group(process, grace_seconds=2)
    stop.assert_called_once_with(handle, timeout=2)
    process.poll.assert_not_called()


@pytest.mark.windows
def test_run_group_reaps_native_process_tree_on_timeout():
    program = (
        "import os, subprocess, sys, time; "
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
        "print(os.getpid(), child.pid, flush=True); time.sleep(60)"
    )
    with pytest.raises(subprocess.TimeoutExpired) as raised:
        terminal_detached_process.run_group(
            [sys.executable, "-c", program], timeout=2, capture_output=True, text=True,
        )

    pids = [int(pid) for pid in raised.value.stdout.split()]
    assert len(pids) == 2

    def alive(pid):
        try:
            return psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
        except psutil.NoSuchProcess:
            return False

    deadline = time.monotonic() + 5
    while any(alive(pid) for pid in pids) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not any(alive(pid) for pid in pids)


@pytest.mark.windows
def test_run_group_defaults_to_noninteractive_stdin():
    completed = terminal_detached_process.run_group(
        [sys.executable, "-c", "import sys; print(repr(sys.stdin.read()))"],
        timeout=5, capture_output=True, text=True, check=True,
    )
    assert completed.stdout.strip() == "''"


@pytest.mark.windows
@pytest.mark.parametrize("stop_failure", [TimeoutError("still alive"), PermissionError("denied")])
def test_run_group_preserves_timeout_and_stderr_if_stop_fails(monkeypatch, stop_failure):
    process = Mock(spec=subprocess.Popen)
    timeout = subprocess.TimeoutExpired(["child"], 5, stderr=b"partial")
    process.communicate.side_effect = timeout
    handle = SimpleNamespace(process=process)
    monkeypatch.setattr(platform_process, "spawn_group", Mock(return_value=handle))
    stop = Mock(side_effect=stop_failure)
    monkeypatch.setattr(platform_process, "stop_group", stop)

    with pytest.raises(subprocess.TimeoutExpired) as raised:
        terminal_detached_process.run_group(["child"], timeout=5, grace_seconds=2)
    assert raised.value is timeout
    assert raised.value.stderr == b"partial"
    assert str(stop_failure) in raised.value.__notes__[0]
    stop.assert_called_once_with(handle, timeout=2)
    process.communicate.assert_called_once_with(timeout=5)
