"""Greeters, closing logins and foreign XFCE processes are not fixture desktops."""

import os
import subprocess

import pytest

from yoke_harness import linux_desktop_state as state


@pytest.mark.posix_only(reason="runs on the remote Linux test machine")
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


@pytest.mark.posix_only(reason="runs on the remote Linux test machine")
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
    sessions = state.desktop_sessions()
    assert bool(sessions) is expected
    if expected:
        assert sessions[0]["environment"]["GDK_BACKEND"] == "x11"


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
    assert calls == [["loginctl", "terminate-session", "c2", "--no-pager"]]


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


GONE = "Failed to get session path: No session 'c8' known\n"


def fake_loginctl(monkeypatch, lists, show=None, terminate=None):
    """Answer each list-sessions with the next listing; record terminations."""
    listings = iter(lists)
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        if argv[1] == "list-sessions":
            return subprocess.CompletedProcess(argv, 0, next(listings), "")
        if argv[1] == "show-session":
            return show(argv)
        return terminate(argv)

    monkeypatch.setattr(state.subprocess, "run", run)
    return calls


def answer(code, stderr=""):
    return lambda argv: subprocess.CompletedProcess(argv, code, "", stderr)


def active_show(argv):
    if argv[2] == "c8":
        return subprocess.CompletedProcess(argv, 1, "", GONE)
    output = f"Type=x11\nState=active\nClass=user\nUser={os.getuid()}\n"
    return subprocess.CompletedProcess(argv, 0, output, "")


@pytest.mark.posix_only(reason="runs on the remote Linux test machine")
def test_session_that_logs_out_between_list_and_show_is_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "Path", lambda value: tmp_path)
    fake_loginctl(
        monkeypatch,
        ["c8 1000 fixture\nc2 1000 fixture\n", "c2 1000 fixture\n"],
        active_show,
    )
    assert [row["id"] for row in state.graphical_sessions()] == ["c2"]


@pytest.mark.posix_only(reason="runs on the remote Linux test machine")
@pytest.mark.parametrize(
    "relisted,stderr",
    [("c8 1000 fixture\n", GONE), ("", "Access denied\n")],
    ids=["still-listed", "other-error"],
)
def test_show_session_failure_on_a_listed_or_unexplained_session_stays_unknown(
    tmp_path, monkeypatch, relisted, stderr
):
    monkeypatch.setattr(state, "Path", lambda value: tmp_path)
    fake_loginctl(monkeypatch, ["c8 1000 fixture\n", relisted], answer(1, stderr))
    with pytest.raises(RuntimeError, match="linux_desktop_state_unknown: " + stderr):
        state.graphical_sessions()


@pytest.mark.parametrize("relisted", ["", "c8 1000 fixture\n"], ids=["gone", "listed"])
def test_terminate_failure_on_a_session_already_gone_is_stopped(
    monkeypatch, tmp_path, relisted
):
    marker = tmp_path / "ownership"
    marker.write_text("{}")
    live = iter([[{"id": "c8"}], []])
    monkeypatch.setattr(state, "desktop_sessions", lambda **kw: [])
    monkeypatch.setattr(state, "graphical_sessions", lambda: next(live))
    monkeypatch.setattr(state, "ownership_file", lambda: marker.open("r+"))
    fake_loginctl(monkeypatch, [relisted], terminate=answer(1, GONE))
    if relisted:
        with pytest.raises(RuntimeError, match="linux_desktop_stop_failed"):
            state.stop_desktop()
        return
    state.stop_desktop()
    assert marker.read_text() == ""


def test_session_active_past_the_limit_still_refuses_stop(monkeypatch):
    clock = iter([0.0, state.DESKTOP_READY_TIMEOUT_SECONDS + 1])
    monkeypatch.setattr(state.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(state, "desktop_sessions", lambda **kw: [])
    monkeypatch.setattr(state, "graphical_sessions", lambda: [{"id": "c2"}])
    fake_loginctl(monkeypatch, [], terminate=answer(0))
    with pytest.raises(RuntimeError, match="linux_desktop_stop_not_proved"):
        state.stop_desktop()
