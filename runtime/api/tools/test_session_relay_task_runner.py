"""The generated Windows relay task runner: windowless, stdio-free, self-restarting."""

import ast
import io
import subprocess
import sys
import time

import pytest

from runtime.api.tools.session_relay_release_test_support import relay_instance
from runtime.api.tools.test_session_relay_task_scheduler import Scheduler
from yoke_core.tools import session_relay_task_pins as pins
from yoke_core.tools import session_relay_task_runner as task_runner
from yoke_core.tools import session_relay_task_scheduler as tasks

pytestmark = pytest.mark.windows
SID = "S-1-5-21-123-456-789-1001"


class _Stop(Exception):
    pass


def _source(tmp_path):
    return task_runner.relay_task_runner_source(
        environment={"YOKE_X": "1"},
        argv=["relay.exe", "--env", "prod", "relay", "serve"],
        stdout_log=tmp_path / "relay.out.log",
        stderr_log=tmp_path / "relay.err.log",
        contain=False,
    )


def _run(source, monkeypatch, codes, *, clock=None, sleeps=None, stop_after=None):
    calls, slept = [], [] if sleeps is None else sleeps
    results = iter(codes)

    def call(argv, **kwargs):
        calls.append((argv, kwargs))
        try:
            return next(results)
        except StopIteration:
            raise _Stop()

    def sleep(seconds):
        slept.append(seconds)
        if stop_after is not None and len(slept) >= stop_after:
            raise _Stop()

    monkeypatch.setattr(subprocess, "call", call)
    monkeypatch.setattr(time, "sleep", sleep)
    if clock is not None:
        monkeypatch.setattr(time, "monotonic", clock)
    monkeypatch.setattr(tasks.os, "environ", {})
    with pytest.raises(_Stop):
        exec(compile(source, "task-runner.py", "exec"), {})
    return calls, slept


def test_relay_starts_with_no_window_and_no_inherited_stdio(tmp_path, monkeypatch):
    calls, _ = _run(_source(tmp_path), monkeypatch, [])
    argv, kwargs = calls[0]
    assert argv == ["relay.exe", "--env", "prod", "relay", "serve"]
    assert kwargs["stdin"] is subprocess.DEVNULL
    assert kwargs["stdout"].name == str(tmp_path / "relay.out.log")
    assert kwargs["stderr"].name == str(tmp_path / "relay.err.log")
    expected = task_runner.CREATE_NO_WINDOW if tasks.os.name == "nt" else 0
    assert kwargs["creationflags"] == expected
    assert tasks.os.environ == {"YOKE_X": "1"}


def test_any_relay_exit_restarts_it_with_backoff_until_the_task_ends(tmp_path, monkeypatch, capsys):
    calls, slept = _run(
        _source(tmp_path), monkeypatch,
        [task_runner.WINDOWS_RELAY_RESTART_CODE, 0, 1, -1073741510, 3, 4, 5, 6, 7],
    )
    assert len(calls) == 10
    # The release-follow code restarts at once; every other exit backs off.
    assert slept == [2, 4, 8, 16, 32, 60, 60, 60]
    assert "relay_exited_unexpectedly: exit -1073741510; the task runner restarts it in 8s" in (
        capsys.readouterr().err
    )


def test_a_relay_that_ran_long_restarts_at_the_shortest_delay(tmp_path, monkeypatch):
    ticks = iter([0, 1, 2, 3, 4, 4 + task_runner.RELAY_HEALTHY_RUN_SECONDS, 400])
    _, slept = _run(_source(tmp_path), monkeypatch, [1, 1, 1], clock=lambda: next(ticks))
    assert slept == [2, 4, 1]


def test_windowless_runner_writes_its_own_messages_to_the_stderr_log(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)  # pythonw: no stdio at all
    _run(_source(tmp_path), monkeypatch, [9], stop_after=1)
    assert isinstance(sys.stderr, io.TextIOWrapper) and sys.stdout is sys.stderr
    sys.stderr.close()
    log = (tmp_path / "relay.err.log").read_text(encoding="utf-8")
    assert "relay_exited_unexpectedly: exit 9" in log


def test_installed_runner_keeps_its_pins_readable_as_data(tmp_path, monkeypatch):
    instance = relay_instance(tmp_path)
    runner = Scheduler(instance)
    monkeypatch.setattr(tasks.relay_install, "converge_relay_launcher", lambda *a, **k: tmp_path / "yoke.cmd")
    tasks.install_relay_task(instance=instance, runner=runner)
    source = (instance.state_dir / "task-runner.py").read_text(encoding="utf-8")
    ast.parse(source)
    document = tasks.ET.fromstring(runner.xml)
    pinned = pins.task_pins(document, instance.label)
    assert pinned.state_dir == instance.state_dir
    assert pinned.config == str(instance.config_path)
    assert pinned.argv[-2:] == ["relay", "serve"]


def test_containment_joins_a_kill_on_close_job_only_as_the_task():
    compile(task_runner.CONTAIN_RUNNER, "task-runner.py", "exec")
    # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | JOB_OBJECT_LIMIT_BREAKAWAY_OK
    assert "_info.basic.flags = 0x2000 | 0x800" in task_runner.CONTAIN_RUNNER
    exec(task_runner.CONTAIN_RUNNER, {"__name__": "imported"})  # never contains an importer


@pytest.mark.windows_only(reason="Win32 job objects")
def test_containment_runs_on_windows():
    probe = f"exec({task_runner.CONTAIN_RUNNER!r}, {{'__name__': '__main__'}}); print('contained')"
    result = subprocess.run([sys.executable, "-I", "-c", probe], capture_output=True, text=True, timeout=60)
    assert (result.returncode, result.stdout.strip()) == (0, "contained"), result.stderr
