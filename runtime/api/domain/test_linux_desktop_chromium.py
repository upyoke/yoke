"""The host-side desktop Chromium driver: shipped program, DevTools and refusals."""

from __future__ import annotations

import json
import os
import shlex
import socket
import struct
import subprocess
import sys
import threading

import pytest

from yoke_harness import linux_desktop_chromium as host
from yoke_harness import ssh_linux_browser_approval as controller
from yoke_harness.linux_devtools_page import DevToolsPage

START = "https://app.example/connect?user_code=AB12-CD34"


def _shipped_program(argv):
    captured = {}

    def run(command, timeout):
        captured["argv"] = command
        return subprocess.CompletedProcess(
            command, 0, '{"ok": true, "quit": false}', ""
        )

    controller._host(
        type("Control", (), {"_run": staticmethod(run)}), *argv, desktop=False
    )
    return shlex.split(captured["argv"])[2]


def test_shipped_program_runs_with_only_the_host_stdlib(tmp_path):
    program = _shipped_program(["quit"])
    assert "from yoke_harness" not in program
    result = subprocess.run(
        [sys.executable, "-I", "-c", program, "unregistered"],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert result.returncode == 69
    assert (
        json.loads(result.stdout)["reason"] == "linux_desktop_chromium_command_unknown"
    )


def _frame(payload: bytes) -> bytes:
    size = len(payload)
    if size < 126:
        return bytes([0x81, size]) + payload
    return bytes([0x81, 126]) + struct.pack(">H", size) + payload


def _unmask(connection) -> dict:
    first, second = connection.recv(2)
    size = second & 0x7F
    if size == 126:
        size = struct.unpack(">H", connection.recv(2))[0]
    mask = connection.recv(4)
    data = b""
    while len(data) < size:
        data += connection.recv(size - len(data))
    return json.loads(bytes(b ^ mask[i % 4] for i, b in enumerate(data)))


def test_devtools_page_masks_requests_and_reassembles_replies():
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    received = []

    def serve():
        connection, _ = server.accept()
        with connection:
            request = b""
            while b"\r\n\r\n" not in request:
                request += connection.recv(1024)
            connection.sendall(b"HTTP/1.1 101 Switching Protocols\r\n\r\n")
            message = _unmask(connection)
            received.append(message)
            event = json.dumps({"method": "Page.loadEventFired"}).encode()
            reply = json.dumps(
                {"id": message["id"], "result": {"result": {"value": "x" * 300}}}
            ).encode()
            # An unrelated event, then the reply split across two fragments.
            connection.sendall(_frame(event))
            connection.sendall(bytes([0x01, 10]) + reply[:10])
            rest = reply[10:]
            connection.sendall(bytes([0x80, 126]) + struct.pack(">H", len(rest)) + rest)

    thread = threading.Thread(target=serve)
    thread.start()
    port = server.getsockname()[1]
    page = DevToolsPage(f"ws://127.0.0.1:{port}/devtools/page/1")
    reply = page.call("Runtime.evaluate", expression="1")
    thread.join(5)
    server.close()
    assert received[0]["method"] == "Runtime.evaluate"
    assert reply == {"result": {"value": "x" * 300}}


class _Page:
    def __init__(self, values):
        self.values = list(values)
        self.expressions = []

    def call(self, method, **params):
        self.expressions.append(params["expression"])
        return {"result": {"value": self.values.pop(0)}}


def _approve(monkeypatch, *, values, urls_after):
    page = _Page(values)
    lists = iter(
        [[{"id": "T1", "type": "page", "url": START, "webSocketDebuggerUrl": "ws://x"}]]
        + urls_after
    )
    monkeypatch.setattr(host, "devtools_port", lambda: 9222)
    monkeypatch.setattr(host, "_pages", lambda port: next(lists))
    monkeypatch.setattr(host, "DevToolsPage", lambda url: page)
    monkeypatch.setattr(host, "urlopen", lambda url, timeout: _Closing())
    monkeypatch.setattr(host.time, "sleep", lambda _s: None)
    return host.approve([START], "Approve machine"), page


class _Closing:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_approval_presses_only_after_revalidating_the_tab(monkeypatch):
    result, page = _approve(
        monkeypatch,
        values=["approval_control_missing", "pressed"],
        urls_after=[[{"id": "T1", "url": "https://app.example/orgs/acme/frontier"}]],
    )
    assert result == {
        "state": "approved",
        "starting_url": START,
        "result_url": "https://app.example/orgs/acme/frontier",
    }
    assert f"location.href !== {json.dumps(START)}" in page.expressions[0]
    assert '"Approve machine"' in page.expressions[0]


@pytest.mark.parametrize("state", ["browser_tab_changed"])
def test_a_changed_tab_is_never_pressed(monkeypatch, state):
    result, page = _approve(monkeypatch, values=[state], urls_after=[])
    assert result == {"state": "browser_tab_changed"}
    assert len(page.expressions) == 1


def test_approval_without_navigation_is_reported(monkeypatch):
    unchanged = [[{"id": "T1", "url": START}]] * host.NAVIGATION_ATTEMPTS
    result, _ = _approve(monkeypatch, values=["pressed"], urls_after=unchanged)
    assert result == {"state": "approval_navigation_missing"}


def test_missing_tab_is_reported_without_pressing(monkeypatch):
    monkeypatch.setattr(host, "devtools_port", lambda: 9222)
    monkeypatch.setattr(
        host, "_pages", lambda port: [{"id": "T2", "url": "https://other.example/"}]
    )
    monkeypatch.setattr(host, "DevToolsPage", lambda url: pytest.fail("pressed"))
    assert host.approve([START], "Approve machine") == {"state": "browser_tab_missing"}


def test_prepare_refuses_when_the_default_browser_is_not_chromium(monkeypatch):
    monkeypatch.setattr(host, "_default_browser", lambda: "firefox.desktop")
    monkeypatch.setattr(host, "_desktop_env", lambda: dict(os.environ))
    with pytest.raises(host.ChromiumRefusal) as refusal:
        host.prepare()
    assert refusal.value.reason == "linux_desktop_default_browser_not_chromium"
    assert "provision_linux_desktop.py" in refusal.value.recovery


def _sensible_desktop(tmp_path, monkeypatch):
    applications = tmp_path / "applications"
    applications.mkdir()
    (applications / "debian-sensible-browser.desktop").write_text(
        "[Desktop Entry]\nExec=sensible-browser %u\n"
    )
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_DATA_DIRS", str(tmp_path))
    monkeypatch.setattr(
        host, "_default_browser", lambda: "debian-sensible-browser.desktop"
    )


def test_prepare_follows_debian_sensible_browser_to_chromium(monkeypatch, tmp_path):
    _sensible_desktop(tmp_path, monkeypatch)
    chromium = tmp_path / "chromium"
    chromium.write_text("")
    launched = []
    ports = iter([None, 9222])

    def which(name, path=None):
        if name == "sensible-browser":
            return "/usr/bin/sensible-browser"
        if name == "x-www-browser":
            return str(chromium)
        return None

    monkeypatch.setattr(host.shutil, "which", which)
    monkeypatch.setattr(host, "devtools_port", lambda: next(ports))
    monkeypatch.setattr(host, "quit_chromium", lambda: False)
    monkeypatch.setattr(host, "user_data_dirs", lambda: (tmp_path,))
    monkeypatch.setattr(host, "_desktop_env", lambda: {"DISPLAY": ":11"})
    monkeypatch.setattr(
        host.subprocess, "Popen", lambda argv, **kw: launched.append((argv, kw.get("env")))
    )
    monkeypatch.setattr(host.time, "sleep", lambda _s: None)
    assert host.prepare() == {"chromium": "started"}
    assert launched == [
        ([str(chromium.resolve()), "--remote-debugging-port=0"], {"DISPLAY": ":11"})
    ]


def test_prepare_refuses_a_dispatcher_that_does_not_launch_chromium(monkeypatch, tmp_path):
    _sensible_desktop(tmp_path, monkeypatch)
    firefox = tmp_path / "firefox"
    firefox.write_text("")

    def which(name, path=None):
        if name == "sensible-browser":
            return "/usr/bin/sensible-browser"
        if name == "x-www-browser":
            return str(firefox)
        return None

    monkeypatch.setattr(host.shutil, "which", which)
    with pytest.raises(host.ChromiumRefusal) as refusal:
        host.prepare()
    assert refusal.value.reason == "linux_desktop_default_browser_not_chromium"
    assert "debian-sensible-browser.desktop" in refusal.value.recovery


def test_prepare_restarts_a_running_chromium_with_a_devtools_port(
    monkeypatch, tmp_path
):
    ports = iter([None, None, 9222])
    launched = []
    monkeypatch.setattr(host, "_default_browser", lambda: "chromium.desktop")
    monkeypatch.setattr(host, "devtools_port", lambda: next(ports))
    monkeypatch.setattr(
        host.shutil,
        "which",
        lambda name: "/usr/bin/chromium" if name == "chromium" else None,
    )
    monkeypatch.setattr(host, "quit_chromium", lambda: True)
    monkeypatch.setattr(host, "user_data_dirs", lambda: (tmp_path,))
    monkeypatch.setattr(
        host,
        "_desktop_env",
        lambda: {"XDG_DATA_DIRS": "/snap/data", "DISPLAY": ":11"},
    )
    monkeypatch.setattr(
        host.subprocess,
        "Popen",
        lambda argv, **kw: launched.append((argv, kw.get("env"))),
    )
    monkeypatch.setattr(host.time, "sleep", lambda _s: None)
    assert host.prepare() == {"chromium": "restarted"}
    assert launched == [
        (
            ["/usr/bin/chromium", "--remote-debugging-port=0"],
            {"XDG_DATA_DIRS": "/snap/data", "DISPLAY": ":11"},
        )
    ]


def test_prepare_reuses_a_debuggable_chromium(monkeypatch):
    monkeypatch.setattr(host, "_default_browser", lambda: "chromium.desktop")
    monkeypatch.setattr(host, "devtools_port", lambda: 9222)
    monkeypatch.setattr(host, "quit_chromium", lambda: pytest.fail("restarted"))
    assert host.prepare() == {"chromium": "reused"}


def test_quit_is_graceful_and_names_a_chromium_that_stays(monkeypatch):
    signals = []
    monkeypatch.setattr(host, "browser_pids", lambda: [41])
    monkeypatch.setattr(
        host.os, "kill", lambda pid, signum: signals.append((pid, signum))
    )
    clock = [0.0]

    def monotonic():
        clock[0] += host.QUIT_WAIT_SECONDS
        return clock[0]

    monkeypatch.setattr(host.time, "monotonic", monotonic)
    monkeypatch.setattr(host.time, "sleep", lambda _s: None)
    with pytest.raises(host.ChromiumRefusal) as refusal:
        host.quit_chromium()
    assert signals == [(41, host.signal.SIGTERM)]
    assert refusal.value.reason == "linux_desktop_chromium_quit_not_proved"
    assert "not force-killed" in refusal.value.recovery


def test_default_browser_reads_xdg_settings_in_a_login_shell(monkeypatch):
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(
            argv, 0, "banner\nYOKE_DESKTOP_BROWSER:0:chromium_chromium.desktop", ""
        )

    monkeypatch.setattr(host.subprocess, "run", run)
    assert host._default_browser() == "chromium_chromium.desktop"
    assert calls == [
        [
            "bash",
            "-lc",
            "browser=$(xdg-settings get default-web-browser); "
            'printf "YOKE_DESKTOP_BROWSER:%s:%s" "$?" "$browser"',
        ]
    ]


def test_chromium_launch_env_uses_the_login_shell_data_dirs(monkeypatch):
    def run(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 0, "YOKE_DESKTOP_XDG:/snap/data", "")

    monkeypatch.setenv("XDG_DATA_DIRS", "/usr/share")
    monkeypatch.setattr(host.subprocess, "run", run)
    env = host._desktop_env()
    assert env["XDG_DATA_DIRS"] == "/snap/data"
    assert env["XDG_DATA_DIRS"] != "/usr/share"


def test_missing_login_shell_names_the_session_environment(monkeypatch):
    def run(argv, **kwargs):
        raise OSError("bash missing")

    monkeypatch.setattr(host.subprocess, "run", run)
    with pytest.raises(host.ChromiumRefusal) as refusal:
        host._default_browser()
    assert refusal.value.reason == "linux_desktop_session_environment_unavailable"
    assert "bash -lc" in refusal.value.recovery
