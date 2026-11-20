"""Uninstall closes the browsers Yoke started, or stops before changing anything."""

from types import SimpleNamespace

import pytest

from yoke_cli.config import machine_uninstall_browsers as browsers
from yoke_cli.config.machine_uninstall_inventory import UninstallError
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
    assert output == ["browsers: closed 1 identity browser(s) and 1 Browser QA daemon(s)"]


def test_identity_browser_that_stays_open_refuses(machine):
    open_ports, _closed, _stopped, _daemon, monkeypatch = machine
    monkeypatch.setattr(devtools, "close", lambda port: None)
    monkeypatch.setattr(browsers, "CLOSE_SECONDS", 0)
    with pytest.raises(UninstallError, match="uninstall_browser_running.*9222.*nothing else was changed"):
        browsers.stop(lambda line: None)


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
