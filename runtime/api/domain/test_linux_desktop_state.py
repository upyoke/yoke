"""Greeters, closing logins and foreign XFCE processes are not fixture desktops."""

import os
import subprocess

import pytest

from yoke_harness import linux_desktop_state as state


@pytest.mark.parametrize(
    "kind,status,cls,user,expected",
    [
        ("x11", "active", "user", "fixture", True),
        ("wayland", "active", "user", "fixture", True),
        ("x11", "active", "greeter", "fixture", False),
        ("x11", "closing", "user", "fixture", False),
        ("x11", "online", "user", "fixture", False),
        ("x11", "active", "user", "other", False),
        ("tty", "active", "user", "fixture", False),
    ],
)
def test_only_active_logged_in_fixture_graphical_sessions(
    tmp_path, monkeypatch, kind, status, cls, user, expected
):
    monkeypatch.setattr(state, "Path", lambda value: tmp_path)
    uid = os.getuid() if user == "fixture" else os.getuid() + 1

    def run(argv, **kwargs):
        output = (
            "c2\n"
            if "list-sessions" in argv
            else f"Type={kind}\nState={status}\nClass={cls}\nUser={uid}\n"
        )
        return subprocess.CompletedProcess(argv, 0, output, "")

    monkeypatch.setattr(state.subprocess, "run", run)
    assert bool(state.graphical_sessions()) is expected


@pytest.mark.parametrize(
    "active,foreign,expected",
    [(True, False, True), (False, False, False), (True, True, False)],
)
def test_xfce_process_must_belong_to_active_fixture_login(
    tmp_path, monkeypatch, active, foreign, expected
):
    proc = tmp_path / "proc"
    process = proc / "42"
    process.mkdir(parents=True)
    (process / "comm").write_text("xfce4-session")
    (process / "environ").write_bytes(b"DISPLAY=:10\0XDG_SESSION_ID=c2\0")
    (process / "stat").write_text("42 (xfce4-session) " + " ".join(["1"] * 20))
    path_type = type(tmp_path)

    def path(value):
        return proc if str(value) == "/proc" else path_type(value)

    path.home = lambda: tmp_path
    monkeypatch.setattr(state, "Path", path)
    monkeypatch.setattr(
        state, "graphical_sessions", lambda: [{"id": "c2"}] if active else []
    )
    if foreign:
        monkeypatch.setattr(state.os, "getuid", lambda: process.stat().st_uid + 1)
    assert bool(state.desktop_sessions()) is expected


def test_reset_ends_active_wayland_session(monkeypatch, tmp_path):
    live = [{"id": "c2"}]
    marker = tmp_path / "ownership"
    marker.touch()
    monkeypatch.setattr(state, "desktop_sessions", lambda **kw: [])
    monkeypatch.setattr(state, "graphical_sessions", lambda: live)
    monkeypatch.setattr(state, "ownership_file", lambda: marker.open("r+"))
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        live.clear()
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(state.subprocess, "run", run)
    state.stop_desktop()
    assert calls == [["loginctl", "terminate-session", "c2"]]


def test_reset_does_not_signal_a_recycled_xfce_process(monkeypatch, tmp_path):
    session = {"pid": 42, "start": "old"}
    observations = iter([[session], [{**session, "start": "new"}], []])
    marker = tmp_path / "ownership"
    marker.touch()
    monkeypatch.setattr(state, "desktop_sessions", lambda **kw: next(observations))
    monkeypatch.setattr(state, "graphical_sessions", lambda: [])
    monkeypatch.setattr(state, "ownership_file", lambda: marker.open("r+"))
    monkeypatch.setattr(state.os, "kill", lambda *a: pytest.fail("recycled PID"))
    state.stop_desktop()
