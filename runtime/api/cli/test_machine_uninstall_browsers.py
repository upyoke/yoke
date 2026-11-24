"""Uninstall closes the browsers Yoke started, or stops before changing anything."""

from types import SimpleNamespace

import psutil
import pytest

from yoke_cli.config import machine_uninstall_browsers as browsers
from yoke_cli.config.machine_uninstall_inventory import Inventory, UninstallError
from yoke_cli.config import machine_uninstall_steps as steps
from yoke_harness import browser_client, browser_runtime_home
from yoke_harness import identity_browser_devtools as devtools


@pytest.fixture
def machine(tmp_path, monkeypatch):
    """One identity browser on port 9222 and one running QA daemon."""
    open_ports, closed, stopped = [9222], [], []
    state_file = tmp_path / "daemons" / "abc" / ".daemon-state.json"
    state_file.parent.mkdir(parents=True)
    state_file.write_text("{}")
    daemon = SimpleNamespace(pid=41, profile_dir="/profiles/qa", running=True)
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path))
    monkeypatch.setattr(psutil, "process_iter", lambda: iter(()))
    monkeypatch.setattr(browser_runtime_home, "runtime_dir", lambda: tmp_path)
    monkeypatch.setattr(devtools, "live_ports", lambda: list(open_ports))

    def close(port):
        closed.append(port)
        open_ports.remove(port)

    def daemon_stop(*, profile_dir):
        stopped.append(profile_dir)
        daemon.running = False

    monkeypatch.setattr(devtools, "close", close)
    monkeypatch.setattr(browser_client.DaemonState, "load", lambda path: daemon)
    monkeypatch.setattr(browser_client, "daemon_running", lambda state: state.running)
    monkeypatch.setattr(browser_client, "daemon_stop", daemon_stop)
    return open_ports, closed, stopped, daemon, monkeypatch


def test_closes_identity_browsers_and_qa_daemons(machine):
    _open, closed, stopped, _daemon, _patch = machine
    output = []
    browsers.stop(output.append)
    assert closed == [9222] and stopped == ["/profiles/qa"]
    assert output == ["browsers: stopped Browser QA daemon (PID 41)"]


class Process:
    def __init__(self, pid, executable, *, survives=False):
        self.pid = pid
        self.executable = executable
        self.survives = survives
        self.killed = False

    def exe(self):
        if isinstance(self.executable, Exception):
            raise self.executable
        return str(self.executable)

    def kill(self):
        if self.survives:
            raise psutil.AccessDenied(self.pid)
        self.killed = True


def test_stops_cached_processes_after_the_devtools_port_closes(machine, tmp_path):
    open_ports, _closed, _stopped, _daemon, monkeypatch = machine
    cache = tmp_path / "playwright-cache" / "yoke"
    cached = cache / "chromium" / "chrome.exe"
    browser = Process(9222, cached)
    orphan = Process(9223, cached)
    ignored = [
        Process(9224, cache.with_name("yoke-unrelated") / "chrome.exe"),
        Process(9225, tmp_path / "relay-state" / "python.exe"),
        Process(9226, psutil.AccessDenied(9226)),
        Process(9227, psutil.NoSuchProcess(9227)),
        Process(browsers.os.getpid(), cached),
        Process(9228, cached),
    ]
    waits = []

    def wait(processes, *, timeout):
        assert not open_ports
        waits.append((set(processes), timeout))
        if len(waits) == 1:
            return [browser], [orphan]
        assert orphan.killed
        return [orphan], []

    monkeypatch.setattr(psutil, "process_iter", lambda: iter([browser, orphan, *ignored]))
    monkeypatch.setattr(psutil, "wait_procs", wait)
    monkeypatch.setattr(
        browsers.platform_process, "ancestors", lambda pid: [SimpleNamespace(pid=9228)]
    )
    output = []
    browsers.stop(output.append)
    assert waits == [({browser, orphan}, 10), ({orphan}, 10)]
    assert not browser.killed and all(not process.killed for process in ignored)
    assert output[-2:] == [
        "browsers: stopped chrome.exe (PID 9222)",
        "browsers: stopped chrome.exe (PID 9223)",
    ]


def test_kill_denied_refuses_before_relay_or_project_steps(machine, tmp_path):
    _open, _closed, _stopped, daemon, monkeypatch = machine
    daemon.running = False
    config = tmp_path / "config.json"
    config.write_text("{}")
    inventory = Inventory(tmp_path, config, (), ("remote",), False, None, ())
    browser = Process(9223, tmp_path / "playwright-cache" / "yoke" / "chrome.exe", survives=True)
    monkeypatch.setattr(psutil, "process_iter", lambda: iter([browser]))
    monkeypatch.setattr(psutil, "wait_procs", lambda processes, *, timeout: ([], processes))

    def later_step(*args):
        pytest.fail("uninstall reached a later step")

    monkeypatch.setattr(steps.machine_uninstall_projects, "preflight", later_step)
    monkeypatch.setattr(steps, "command", later_step)
    output = []
    assert steps.remove(inventory, (), output.append) == 1
    assert config.read_text() == "{}"
    assert "uninstall_browser_running: could not stop chrome.exe (PID 9223)" in output[0]
    assert "nothing else changed" in output[1]


def test_daemon_that_survives_stop_refuses(machine):
    _open, _closed, _stopped, daemon, monkeypatch = machine
    monkeypatch.setattr(browser_client, "daemon_stop", lambda *, profile_dir: None)
    with pytest.raises(UninstallError, match="Browser QA daemon PID 41 did not stop"):
        browsers.stop(lambda line: None)


def test_nothing_running_reports_nothing(machine):
    open_ports, _closed, _stopped, daemon, _patch = machine
    open_ports.clear()
    daemon.running = False
    output = []
    browsers.stop(output.append)
    assert output == []


def test_devtools_close_sends_browser_close_and_tolerates_a_dropped_socket(monkeypatch):
    sent = []

    class Page:
        def __init__(self, url):
            sent.append(url)
            self.socket = SimpleNamespace(close=lambda: sent.append("closed"))

        def call(self, method):
            sent.append(method)
            raise OSError("DevTools closed the page connection")

    monkeypatch.setattr(devtools, "DevToolsPage", Page)
    monkeypatch.setattr(
        devtools, "_get_json", lambda port, path: {"webSocketDebuggerUrl": f"ws://127.0.0.1:{port}/b"}
    )
    devtools.close(9222)
    assert sent == ["ws://127.0.0.1:9222/b", "Browser.close", "closed"]
    monkeypatch.setattr(devtools, "_get_json", lambda port, path: (_ for _ in ()).throw(OSError("gone")))
    devtools.close(9222)  # A browser that already exited is not an error.
