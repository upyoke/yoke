"""Uninstall waits for an ended relay task's process tree before removing files."""

import subprocess

import pytest

from runtime.api.tools.session_relay_release_test_support import relay_instance
from runtime.api.tools.test_session_relay_task_scheduler import Scheduler
from yoke_contracts.platform_process import ProcessInfo
from yoke_core.tools import session_relay_task_scheduler as tasks
from yoke_core.tools import session_relay_task_stop as stop

pytestmark = pytest.mark.windows


def _process(pid, *argv):
    return ProcessInfo(pid, 1, list(argv), 0.0, "python.exe", 0, "user", 0.0)


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class LingeringScheduler(Scheduler):
    """/End returns while the task stays Running for a few more state reads."""

    def __init__(self, instance, running_reads):
        super().__init__(instance)
        self.running_reads = running_reads
        self.ended = False

    def __call__(self, argv, **kwargs):
        if "/End" in argv:
            self.commands.append(argv)
            self.ended = True
            return subprocess.CompletedProcess(argv, 0, "", "")
        if self.ended and argv[0] == "powershell.exe" and self.state == "4":
            self.running_reads -= 1
            if self.running_reads <= 0:
                self.state = "3"
        return super().__call__(argv, **kwargs)


def _installed(tmp_path, monkeypatch, runner_type=Scheduler, **kwargs):
    instance = relay_instance(tmp_path)
    runner = runner_type(instance, **kwargs)
    monkeypatch.setattr(tasks.relay_install, "converge_relay_launcher",
                        lambda *a, **k: tmp_path / "runtime" / "Scripts" / "yoke.cmd")
    tasks.install_relay_task(instance=instance, runner=runner)
    return instance, runner


def test_uninstall_polls_until_the_ended_task_leaves_running(tmp_path, monkeypatch):
    instance, runner = _installed(tmp_path, monkeypatch, LingeringScheduler, running_reads=3)
    clock = Clock()
    monkeypatch.setattr(stop.time, "monotonic", clock)
    monkeypatch.setattr(stop.time, "sleep", clock.sleep)
    runner.commands.clear()
    status = tasks.uninstall_relay_task(instance=instance, runner=runner, processes=lambda: [])
    assert not status.task_present
    steps = [argv[1] if argv[0] == "schtasks" else "state" for argv in runner.commands
             if argv[0] == "powershell.exe" or argv[1] in {"/End", "/Delete"}]
    end = steps.index("/End")
    assert steps[end:steps.index("/Delete")].count("state") == 3
    assert clock.now > 0


def test_uninstall_waits_for_relay_processes_before_removing_files(tmp_path, monkeypatch):
    instance, runner = _installed(tmp_path, monkeypatch)
    launcher = _process(4100, str(instance.state_dir / "runtime" / "Scripts" / "python.exe"), "-I",
                        str(instance.state_dir / "task-runner.py"))
    unrelated = _process(4200, "python.exe", str(tmp_path / "elsewhere" / "tool.py"))
    tables = [[launcher, unrelated], [launcher, unrelated], [unrelated]]
    snapshots = []

    def processes():
        snapshots.append((instance.state_dir / "task-runner.py").exists())
        return tables.pop(0) if tables else [unrelated]

    monkeypatch.setattr(stop.time, "sleep", lambda seconds: None)
    tasks.uninstall_relay_task(instance=instance, runner=runner, processes=processes)
    assert snapshots == [True, True, True]
    assert not (instance.state_dir / "task-runner.py").exists()


def test_relay_process_outliving_the_bound_fails_naming_its_pid(tmp_path, monkeypatch):
    instance, runner = _installed(tmp_path, monkeypatch)
    worker = _process(5150, str(instance.state_dir / "releases" / "r1" / "python.exe"), "relay")
    clock = Clock()
    monkeypatch.setattr(stop.time, "monotonic", clock)
    monkeypatch.setattr(stop.time, "sleep", clock.sleep)
    with pytest.raises(tasks.RelayInstallError) as raised:
        tasks.uninstall_relay_task(instance=instance, runner=runner, processes=lambda: [worker])
    assert raised.value.code == stop.RELAY_STOP_CODE
    assert "uninstall_relay_not_stopped" in str(raised.value)
    assert "PID 5150" in str(raised.value) and "Recovery:" in str(raised.value)
    assert clock.now >= stop.RELAY_STOP_WAIT_SECONDS
    assert (instance.state_dir / "task-runner.py").exists()
    assert not any("/Delete" in argv for argv in runner.commands)


def test_task_still_running_at_the_bound_fails_naming_the_task(tmp_path, monkeypatch):
    instance, runner = _installed(tmp_path, monkeypatch, LingeringScheduler, running_reads=10**6)
    clock = Clock()
    monkeypatch.setattr(stop.time, "monotonic", clock)
    monkeypatch.setattr(stop.time, "sleep", clock.sleep)
    with pytest.raises(tasks.RelayInstallError, match="uninstall_relay_not_stopped: scheduled task"):
        tasks.uninstall_relay_task(instance=instance, runner=runner, processes=lambda: [])


def test_relay_processes_match_paths_inside_the_state_dir_only(tmp_path):
    state_dir = tmp_path / "relay-instances" / "prod"
    sibling = tmp_path / "relay-instances" / "prod-2" / "python.exe"
    inside = _process(1, str(state_dir / "runtime" / "python.exe"))
    exact = _process(2, "python.exe", str(state_dir))
    beside = _process(3, str(sibling))
    found = stop.relay_processes(state_dir, [inside, exact, beside])
    assert [process.pid for process in found] == [1, 2]
