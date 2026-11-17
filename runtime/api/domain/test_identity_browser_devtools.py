"""The identity-browser approval host program: shipped program, DevTools and refusals."""

from __future__ import annotations

import json
import shlex
import socket
import struct
import subprocess
import sys
import threading

import pytest

from yoke_harness import identity_browser_approval as controller
from yoke_harness import identity_browser_devtools as host
from yoke_harness import linux_desktop_chromium as quitter
from yoke_harness import ssh_linux_browser_approval
from yoke_harness.linux_devtools_page import DevToolsPage

START = "https://app.example/connect?user_code=AB12-CD34"


def _shipped(program_for, argv):
    captured = {}

    def run(command, timeout):
        captured["argv"] = command
        return subprocess.CompletedProcess(command, 0, '{"ok": true}', "")

    program_for(run, argv)
    return shlex.split(captured["argv"])[2]


@pytest.mark.parametrize(
    ("program_for", "reason"),
    [
        (lambda run, argv: controller._host(run, *argv), "identity_browser_command_unknown"),
        (
            lambda run, argv: ssh_linux_browser_approval.quit_desktop_chromium(
                type("Control", (), {"_run": staticmethod(run)})
            ),
            "linux_desktop_chromium_command_unknown",
        ),
    ],
)
def test_shipped_programs_run_with_only_the_host_stdlib(tmp_path, program_for, reason):
    program = _shipped(program_for, ["quit"])
    assert "from yoke_harness" not in program
    assert "from yoke_contracts" not in program
    result = subprocess.run(
        [sys.executable, "-I", "-c", program, "unregistered"],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert result.returncode == 69
    assert json.loads(result.stdout)["reason"] == reason


def test_live_ports_reads_only_answering_identity_browsers(tmp_path, monkeypatch):
    for project, identity, port in (("acme", "operator", "9333"), ("acme", "admin", "9444")):
        profile = tmp_path / host.STORE / project / identity
        profile.mkdir(parents=True)
        (profile / "DevToolsActivePort").write_text(port + "\n/devtools/browser/x\n")
    (tmp_path / host.STORE / "acme" / "stale").mkdir()
    answering = {9333}

    def get_json(port, path):
        if port not in answering:
            raise OSError("refused")
        return {}

    monkeypatch.setattr(host, "_get_json", get_json)
    assert host.live_ports(tmp_path) == [9333]


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
    first = next(lists)
    monkeypatch.setattr(host, "_all_pages", lambda: [(9222, page) for page in first])
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
    monkeypatch.setattr(
        host,
        "_all_pages",
        lambda: [(9222, {"id": "T2", "url": "https://other.example/"})],
    )
    monkeypatch.setattr(host, "DevToolsPage", lambda url: pytest.fail("pressed"))
    assert host.approve([START], "Approve machine") == {"state": "browser_tab_missing"}


def test_close_asks_each_browser_to_close_and_waits(monkeypatch):
    calls = []
    ports = iter([[9222], []])
    monkeypatch.setattr(host, "live_ports", lambda home=None: next(ports, []))
    monkeypatch.setattr(
        host, "_get_json", lambda port, path: {"webSocketDebuggerUrl": "ws://b"}
    )

    class _Browser:
        def __init__(self, url):
            calls.append(url)

        def call(self, method, **params):
            calls.append(method)
            raise OSError("closed while answering")

    monkeypatch.setattr(host, "DevToolsPage", _Browser)
    assert host.close_all() == {"closed": True, "browsers": 1}
    assert calls == ["ws://b", "Browser.close"]


def test_a_browser_that_stays_open_is_named(monkeypatch):
    monkeypatch.setattr(host, "live_ports", lambda home=None: [9222])
    monkeypatch.setattr(host, "_get_json", lambda port, path: {})
    clock = [0.0]

    def monotonic():
        clock[0] += 31
        return clock[0]

    monkeypatch.setattr(host.time, "monotonic", monotonic)
    assert host.close_all() == {"closed": False, "still_running": 1}


def test_quit_is_graceful_and_names_a_chromium_that_stays(monkeypatch):
    processes = quitter.native_processes
    signals = []
    monkeypatch.setattr(processes, "browser_pids", lambda: [41])
    monkeypatch.setattr(
        processes.os, "kill", lambda pid, signum: signals.append((pid, signum))
    )
    clock = [0.0]

    def monotonic():
        clock[0] += quitter.QUIT_WAIT_SECONDS
        return clock[0]

    monkeypatch.setattr(processes.time, "monotonic", monotonic)
    monkeypatch.setattr(processes.time, "sleep", lambda _s: None)
    with pytest.raises(processes.ChromiumRefusal) as refusal:
        quitter.quit_chromium()
    assert signals == [(41, processes.signal.SIGTERM)]
    assert refusal.value.reason == "linux_desktop_chromium_quit_not_proved"
    assert "not force-killed" in refusal.value.recovery
