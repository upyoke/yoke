"""Real process custody plus identity reuse and persisted descendant checks."""
import os
from pathlib import Path
import subprocess
import sys
import time

import psutil
import pytest

from yoke_contracts import platform_process as processes


def test_snapshot_and_ancestry_observe_current_process():
    own = next(p for p in processes.process_command_lines() if p.pid == os.getpid())
    assert own.cmdline and own.start_time > 0 and own.rss_kb > 0 and own.username
    assert processes.pid_alive(own.pid, own.start_time)
    assert not processes.pid_alive(own.pid, own.start_time + 0.001)
    assert processes.ancestors(own.pid)[0].pid == os.getppid()
    assert processes.handle_from_pid(own.pid, own.start_time + 1) is None
    assert not processes.pid_alive(-1)


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
