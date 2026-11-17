"""The ssh-forward desktop route holds a plain ``ssh -N -L`` child for its use."""

from __future__ import annotations

import contextlib

import pytest

from yoke_harness import desktop_access, desktop_forward

SETTINGS = {
    "resource_name": "test-mac",
    "os": "macos",
    "host": "mac.example",
    "user": "admin",
    "desktop_route": "ssh-forward",
    "desktop_protocol": "vnc",
    "desktop_port": "5900",
    "desktop_user": "oxpecker",
}


class FakeSsh:
    def __init__(self, argv, exit_code=None):
        self.argv = argv
        self.exit_code = exit_code
        self.killed = False

    def poll(self):
        return self.exit_code

    def kill(self):
        self.killed = True

    def wait(self):
        return -9


@pytest.fixture()
def forward_env(tmp_path, monkeypatch):
    key = tmp_path / "key"
    key.write_text("k")
    monkeypatch.setattr(
        desktop_forward, "machine_capability_secret_path", lambda *a: key
    )
    monkeypatch.setattr(desktop_access, "known_hosts_path", lambda _h: tmp_path / "kh")
    checked = []
    monkeypatch.setattr(desktop_access, "_check_desktop", lambda *a: checked.append(a))
    spawned = []
    return spawned, checked, monkeypatch


def _spawn(spawned, exit_code=None):
    def popen(argv, **kwargs):
        process = FakeSsh(argv, exit_code)
        spawned.append(process)
        return process

    return popen


def test_forward_holds_plain_ssh_child_and_kills_it_on_exit(forward_env):
    spawned, checked, monkeypatch = forward_env
    monkeypatch.setattr(desktop_forward.subprocess, "Popen", _spawn(spawned))
    monkeypatch.setattr(
        desktop_forward.socket, "create_connection", lambda *a, **k: contextlib.nullcontext()
    )
    with desktop_forward.desktop_forward("project", SETTINGS) as (host, port, user):
        assert (host, user) == ("127.0.0.1", "oxpecker")
        assert not spawned[0].killed
    argv = spawned[0].argv
    assert "-N" in argv and "-f" not in argv and "-M" not in argv
    assert argv[argv.index("-S") + 1] == "none"
    assert f"127.0.0.1:{port}:[127.0.0.1]:5900" in argv
    assert spawned[0].killed
    assert checked == [("127.0.0.1", port, "vnc")]


def test_ssh_exit_before_listening_refuses_by_name(forward_env):
    spawned, _checked, monkeypatch = forward_env
    monkeypatch.setattr(desktop_forward.subprocess, "Popen", _spawn(spawned, 255))
    with pytest.raises(desktop_access.DesktopAccessError, match="desktop_forward_failed"):
        with desktop_forward.desktop_forward("project", SETTINGS):
            pytest.fail("route yielded")
    assert spawned[0].killed


def test_listener_that_never_accepts_times_out_by_name(forward_env):
    spawned, _checked, monkeypatch = forward_env
    monkeypatch.setattr(desktop_forward.subprocess, "Popen", _spawn(spawned))
    monkeypatch.setattr(desktop_forward, "FORWARD_READY_SECONDS", 0)

    def refuse(*a, **k):
        raise ConnectionRefusedError

    monkeypatch.setattr(desktop_forward.socket, "create_connection", refuse)
    with pytest.raises(desktop_access.DesktopAccessError, match="did not accept"):
        with desktop_forward.desktop_forward("project", SETTINGS):
            pytest.fail("route yielded")
    assert spawned[0].killed
