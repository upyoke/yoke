"""Real process custody plus identity reuse and persisted descendant checks."""
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace

import psutil
import pytest

from yoke_contracts import platform_process as processes


pytestmark = pytest.mark.windows


def test_snapshot_and_ancestry_observe_current_process():
    own = next(p for p in processes.process_command_lines() if p.pid == os.getpid())
    assert own.cmdline and own.start_time > 0 and own.rss_kb > 0 and own.username
    assert processes.pid_alive(own.pid, own.start_time)

    assert not processes.pid_alive(own.pid, own.start_time + 0.001)
    assert processes.ancestors(own.pid)[0].pid == os.getppid()
    assert processes.handle_from_pid(own.pid, own.start_time + 1) is None
    assert not processes.pid_alive(-1)


def test_wall_clock_drift_keeps_identity_and_reuse_still_reads_dead(monkeypatch):
    """A clock step shifts create_time(), never the recorded start_identity."""
    identity = processes.start_identity(psutil.Process(os.getpid()))
    drifted = psutil.Process(os.getpid()).create_time() + 1.0
    monkeypatch.setattr(psutil.Process, "create_time", lambda self: drifted)
    assert processes.pid_alive(os.getpid(), identity)
    assert not processes.pid_alive(os.getpid(), identity + 1.0)


def test_spawn_stop_and_restore_record():
    group = processes.spawn_group([sys.executable, '-c', 'import time; time.sleep(60)'], stdout=subprocess.PIPE)
    try:
        assert group.process.stdout is not None
        captured = processes.handle_from_pid(group.pid, group.start_time)
        restored = processes.GroupHandle.from_record(captured.to_record())
        assert restored.process is None
        assert restored.members == captured.members
        assert processes.stop_group(group, 1) is True
        assert processes.pid_alive(group.pid, group.start_time) is False
        assert processes.stop_group(restored, 0.1) is False
    finally:
        if group.process.poll() is None:
            group.process.kill()
            group.process.wait()


def test_persisted_members_survive_leader_exit(tmp_path: Path):
    ready = tmp_path / 'child'
    script = ('import subprocess,sys,time; '
              'p=subprocess.Popen([sys.executable,"-c","import time; time.sleep(60)"]); '
              'open(sys.argv[1],"w",encoding="utf-8").write(str(p.pid)); time.sleep(60)')
    group = processes.spawn_group([sys.executable, '-c', script, str(ready)])
    captured = None
    try:
        deadline = time.monotonic() + 10
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert ready.exists()
        captured = processes.handle_from_pid(group.pid, group.start_time)
        child_pid = int(ready.read_text(encoding='utf-8'))
        assert child_pid in dict(captured.members)
        group.process.kill()
        group.process.wait()
        restored = processes.GroupHandle.from_record(captured.to_record())
        assert processes.stop_group(restored, 0.2)
        assert not processes.pid_alive(child_pid, dict(restored.members)[child_pid])
    finally:
        processes.stop_group(captured or group, 0.2)


def test_invalid_record_and_timeout_refuse():
    with pytest.raises(ValueError, match='invalid_process_identity'):
        processes.GroupHandle.from_record({'pid': 0, 'start_time': 1, 'members': []})
    with pytest.raises(ValueError, match='invalid_stop_timeout'):
        processes.stop_group(processes.GroupHandle(1, 1, ()), -1)


def test_reused_member_is_never_signalled(monkeypatch):
    monkeypatch.setattr(processes, 'pid_alive', lambda *args: False)
    monkeypatch.setattr(psutil, 'Process', lambda *args: pytest.fail('must not access reused PID'))
    assert not processes.stop_group(processes.GroupHandle(123, 1, ((123, 1),)), 0)


def test_capture_handles_exit_during_descendant_snapshot(monkeypatch):
    monkeypatch.setattr(processes, 'pid_alive', lambda *args: True)
    class ExitingProcess:
        def children(self, recursive):
            raise psutil.NoSuchProcess(123)
    monkeypatch.setattr(psutil, 'Process', lambda pid: ExitingProcess())
    assert processes.handle_from_pid(123, 1) is None


class _FakeProcess:
    """A verified member whose liveness ends once it is signalled."""

    def __init__(self, live, events, pid=123, refuse=None):
        self.pid, self.live, self.events, self.refuse = pid, live, events, refuse

    _proc = SimpleNamespace(create_time=lambda monotonic=False: 1)

    def create_time(self):
        return 1

    def children(self, recursive):
        return []

    def send_signal(self, sig):
        pytest.fail('adopted process may share the controller console')

    def terminate(self):
        self.events.append('terminate')
        if self.refuse:
            raise self.refuse(self.pid)
        self.live.discard(self.pid)

    def kill(self):
        self.events.append('kill')
        if self.refuse:
            raise self.refuse(self.pid)
        self.live.discard(self.pid)


def _fake_tree(monkeypatch, live, process):
    monkeypatch.setattr(processes, 'pid_alive', lambda pid, stamp=None: pid in live)
    monkeypatch.setattr(psutil, 'Process', lambda pid: process)


def test_windows_adopted_group_never_signals_shared_console(monkeypatch):
    events, live = [], {123}
    monkeypatch.setattr(processes.os, 'name', 'nt')
    _fake_tree(monkeypatch, live, _FakeProcess(live, events))
    assert processes.stop_group(processes.GroupHandle(123, 1, ((123, 1),)), 0)
    assert events == ['terminate']


def test_member_exiting_during_stop_scan_counts_as_stopped(monkeypatch):
    class Exiting(_FakeProcess):
        def children(self, recursive):
            raise psutil.NoSuchProcess(self.pid)
    events, live = [], {123}
    _fake_tree(monkeypatch, live, Exiting(live, events))
    assert not processes.stop_group(processes.GroupHandle(123, 1, ((123, 1),)), 0)
    assert events == []


def test_signal_refused_by_an_exiting_member_counts_as_stopped(monkeypatch):
    class ExitsWhileRefusing(_FakeProcess):
        def terminate(self):
            self.live.discard(self.pid)  # Windows: an exiting process refuses signals.
            raise psutil.AccessDenied(self.pid)
    events, live = [], {123}
    _fake_tree(monkeypatch, live, ExitsWhileRefusing(live, events))
    assert processes.stop_group(processes.GroupHandle(123, 1, ((123, 1),)), 0)


def test_signal_refused_by_a_surviving_member_raises_permission_error(monkeypatch):
    events, live = [], {123}
    _fake_tree(monkeypatch, live, _FakeProcess(live, events, refuse=psutil.AccessDenied))
    with pytest.raises(PermissionError, match=r'process_access_denied: PIDs \[123\]'):
        processes.stop_group(processes.GroupHandle(123, 1, ((123, 1),)), 0)
    assert events == ['terminate', 'kill']


def _darwin_group(monkeypatch, live, exits_on_killpg):
    """Simulate Darwin's killpg EPERM for a group whose leader is exiting."""
    def killpg(pid, sig):
        if exits_on_killpg:
            live.clear()  # The leader became a zombie between check and signal.
        raise PermissionError(1, 'Operation not permitted')
    monkeypatch.setattr(processes.os, 'name', 'posix')
    monkeypatch.setattr(processes.os, 'killpg', killpg, raising=False)
    return processes.GroupHandle(123, 1, ((123, 1),), _owns_session=True)


def test_group_signal_refused_by_an_exiting_group_counts_as_stopped(monkeypatch):
    events, live = [], {123}
    _fake_tree(monkeypatch, live, _FakeProcess(live, events))
    handle = _darwin_group(monkeypatch, live, exits_on_killpg=True)
    assert processes.stop_group(handle, 0)
    assert events == ['terminate']


def test_group_signal_refused_with_a_surviving_member_raises_permission_error(monkeypatch):
    class Survivor(_FakeProcess):
        def terminate(self):
            self.events.append('terminate')

        def kill(self):
            self.events.append('kill')
    events, live = [], {123}
    _fake_tree(monkeypatch, live, Survivor(live, events))
    handle = _darwin_group(monkeypatch, live, exits_on_killpg=False)
    with pytest.raises(PermissionError, match=r'process_access_denied: PIDs \[123\]'):
        processes.stop_group(handle, 0)
    assert events == ['terminate', 'kill']
