"""Browser lifecycle uses portable process custody across command invocations."""

import json
import os
import sys
import time
from types import SimpleNamespace

import pytest

from yoke_contracts import browser_daemon_process as custody, platform_process
from yoke_harness import browser_client, browser_client_readiness, browser_human_gate
from yoke_core.domain import browser_client as core_client


pytestmark = pytest.mark.windows


def test_daemon_process_record_survives_caller_and_stops_tree(tmp_path):
    group = platform_process.spawn_group(
        [sys.executable, "-c", "import time; time.sleep(60)"]
    )
    try:
        custody.record_group(tmp_path, group)
        assert (
            json.loads((tmp_path / custody.PROCESS_RECORD_NAME).read_text())[
                "start_time"
            ]
            == group.start_time
        )
        custody.stop_recorded_group(tmp_path, group.pid, timeout=2)
        assert not platform_process.pid_alive(group.pid, group.start_time)
    finally:
        platform_process.stop_group(group, 2)


def test_missing_process_record_refuses_without_signalling(monkeypatch, tmp_path):
    monkeypatch.setattr(platform_process, "pid_alive", lambda pid: True)
    monkeypatch.setattr(
        platform_process, "stop_group", lambda *a: pytest.fail("unsafe stop")
    )
    with pytest.raises(RuntimeError, match="browser_daemon_stop_failed.*idle exit"):
        custody.stop_recorded_group(tmp_path, 42)


def test_reused_pid_cannot_stop_the_new_owner(tmp_path):
    # Build a valid but stale identity for this process; never signal its new owner.
    record = {"pid": os.getpid(), "start_time": 1.0, "members": [[os.getpid(), 1.0]]}
    (tmp_path / custody.PROCESS_RECORD_NAME).write_text(json.dumps(record))
    custody.stop_recorded_group(tmp_path, os.getpid(), timeout=0)
    assert platform_process.pid_alive(os.getpid())


@pytest.mark.parametrize("client", [browser_client, core_client])
def test_daemon_liveness_uses_shared_process_observation(monkeypatch, client):
    seen = []
    monkeypatch.setattr(
        platform_process, "pid_alive", lambda pid: seen.append(pid) or True
    )
    assert client.daemon_running(client.DaemonState(pid=123))
    assert seen == [123]


def test_human_gate_uses_shared_process_observation(monkeypatch):
    monkeypatch.setattr(platform_process, "pid_alive", lambda pid: pid == 123)
    assert browser_human_gate._pid_alive(123)
    assert not browser_human_gate._pid_alive(0)


def test_launch_uses_shared_group_and_noninteractive_input(monkeypatch, tmp_path):
    seen = []
    handle = SimpleNamespace(pid=123)
    monkeypatch.setattr(
        platform_process,
        "spawn_group",
        lambda argv, **kw: seen.append((argv, kw)) or handle,
    )
    assert (
        browser_client_readiness.launch_daemon(
            ["node", "daemon.js"], {}, tmp_path / "log"
        )
        is handle
    )
    assert seen[0][1]["stdin"] == -3
    assert "start_new_session" not in seen[0][1]


def test_unavailable_process_observation_names_stop_recovery(monkeypatch, tmp_path):
    def denied(pid):
        raise OSError("process query denied")

    monkeypatch.setattr(platform_process, "pid_alive", denied)
    with pytest.raises(
        RuntimeError, match="browser_daemon_stop_failed.*local process access"
    ):
        custody.stop_recorded_group(tmp_path, 42)


def test_unwritable_custody_record_stops_new_daemon_and_names_recovery(
    monkeypatch, tmp_path
):
    group = SimpleNamespace(process=SimpleNamespace(pid=42))
    stopped = []
    monkeypatch.setattr(browser_client_readiness, "launch_daemon", lambda *a: group)

    def denied(*args):
        raise PermissionError("record is unwritable")

    monkeypatch.setattr(browser_client_readiness, "record_group", denied)
    monkeypatch.setattr(
        platform_process, "stop_group", lambda handle, timeout: stopped.append(handle)
    )
    with pytest.raises(
        RuntimeError, match="browser_daemon_custody_failed.*restore write access"
    ):
        browser_client_readiness.start_daemon(["node"], {}, tmp_path)
    assert stopped == [group]


def test_recorded_descendants_stop_after_the_daemon_leader_exits(tmp_path):
    ready = tmp_path / "child.pid"
    release = tmp_path / "exit-leader"
    script = """
import pathlib, subprocess, sys, time
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
pathlib.Path(sys.argv[1]).write_text(str(child.pid), encoding='utf-8')
while not pathlib.Path(sys.argv[2]).exists():
    time.sleep(.01)
"""
    group = platform_process.spawn_group(
        [sys.executable, "-c", script, str(ready), str(release)]
    )
    try:
        deadline = time.monotonic() + 10
        while not ready.exists():
            if time.monotonic() >= deadline:
                pytest.fail("child did not publish its pid")
            time.sleep(0.01)
        child_pid = int(ready.read_text(encoding="utf-8"))
        custody.record_group(tmp_path, group)
        record = json.loads(
            (tmp_path / custody.PROCESS_RECORD_NAME).read_text(encoding="utf-8")
        )
        child_start = dict(record["members"])[child_pid]
        release.touch()
        group.process.wait(timeout=10)
        assert platform_process.pid_alive(child_pid, child_start)
        custody.stop_recorded_group(tmp_path, group.pid, timeout=2)
        assert not platform_process.pid_alive(child_pid, child_start)
    finally:
        platform_process.stop_group(group, 2)
