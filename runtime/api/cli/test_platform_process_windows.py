"""Windows custody starts suspended and assigns the job before user code runs."""
from types import SimpleNamespace

import pytest
from yoke_contracts import platform_process_windows as windows


pytestmark = pytest.mark.windows


class Function:
    def __init__(self, callback):
        self.callback = callback
    def __call__(self, *args):
        return self.callback(*args)


def test_windows_spawn_assigns_before_resuming(monkeypatch):
    events = []
    api = SimpleNamespace(
        OpenThread=Function(lambda *args: 10),
        ResumeThread=Function(lambda *args: events.append('resume') or 1),
        CloseHandle=Function(lambda *args: events.append('close_thread') or 1),
    )
    job = SimpleNamespace(api=api, assign=lambda p: events.append('assign'),
                          close=lambda: events.append('close_job'))
    process = SimpleNamespace(pid=123, kill=lambda: events.append('kill'),
                              wait=lambda: events.append('wait'))
    def popen(argv, **kwargs):
        assert kwargs['creationflags'] & 4
        assert kwargs['creationflags'] & 512
        events.append('spawn')
        return process
    monkeypatch.setattr(windows, 'Job', lambda: job)
    monkeypatch.setattr(windows.subprocess, 'CREATE_NEW_PROCESS_GROUP', 512, raising=False)
    monkeypatch.setattr(windows.subprocess, 'Popen', popen)
    monkeypatch.setattr(windows.psutil, 'Process', lambda pid: SimpleNamespace(
        create_time=lambda: 12.5, threads=lambda: [SimpleNamespace(id=456)]))
    handle = windows.spawn(['program'], {})
    assert handle.pid == 123 and handle.start_time == 12.5
    assert handle.process is process and handle._job is job
    assert events == ['spawn', 'assign', 'resume', 'close_thread']


def test_windows_assignment_failure_cleans_child_and_job(monkeypatch):
    events = []
    def fail(process):
        raise OSError('job policy')
    job = SimpleNamespace(assign=fail, close=lambda: events.append('close'))
    process = SimpleNamespace(kill=lambda: events.append('kill'), wait=lambda: events.append('wait'))
    monkeypatch.setattr(windows, 'Job', lambda: job)
    monkeypatch.setattr(windows.subprocess, 'CREATE_NEW_PROCESS_GROUP', 512, raising=False)
    monkeypatch.setattr(windows.subprocess, 'Popen', lambda *a, **k: process)
    with pytest.raises(OSError, match='job policy'):
        windows.spawn(['program'], {})
    assert events == ['kill', 'wait', 'close']
