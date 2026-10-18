"""Sesman restart orphans are repaired before a viewer can create a second XFCE."""

import json
from pathlib import Path
import subprocess

import pytest

from runtime.api.domain import test_linux_desktop_session as shared
from runtime.api.domain.test_linux_desktop_session import SESSION, PASSWORD
from yoke_harness import linux_desktop_state as state

host = shared.host


@pytest.fixture
def manager(tmp_path, monkeypatch):
    process = tmp_path / "manager"
    process.mkdir()
    (process / "comm").write_text("xrdp-sesman\n")
    (process / "stat").write_text(
        "42 (xrdp-sesman) " + " ".join(["0"] * 19 + ["200000"])
    )
    real_path = Path
    monkeypatch.setattr(
        state,
        "Path",
        lambda name: process if str(name) == "/proc/50" else real_path(name),
    )
    monkeypatch.setattr(
        state.subprocess,
        "run",
        lambda *a, **kw: subprocess.CompletedProcess([], 0, "50\n", ""),
    )
    return process


def test_newer_session_reuses_without_signal(manager, monkeypatch):
    monkeypatch.setattr(
        state.os, "kill", lambda *a: pytest.fail("live session stopped")
    )
    assert not state.restart_orphan({**SESSION, "start": "300000"}, 3389)


@pytest.mark.parametrize("sessions", [[], [SESSION]])
def test_connected_viewer_refuses_before_reuse_or_restart(host, monkeypatch, sessions):
    monkeypatch.setattr(state, "desktop_sessions", lambda: sessions)
    monkeypatch.setattr(state, "rdp_connected", lambda port: True)
    monkeypatch.setattr(
        state, "restart_orphan", lambda *a: pytest.fail("viewer takeover")
    )
    with pytest.raises(
        RuntimeError, match="linux_desktop_viewer_connected:.*close the open"
    ):
        state.ensure_desktop(PASSWORD, rdp_access=True)


def test_gui_command_reuses_desktop_while_viewer_connected(host, monkeypatch):
    monkeypatch.setattr(state, "desktop_sessions", lambda: [SESSION])
    monkeypatch.setattr(state, "rdp_connected", lambda port: True)
    assert state.ensure_desktop(PASSWORD)["desktop_session"] == "reused"


def test_orphan_signals_only_same_fixture_session_and_waits(manager, monkeypatch):
    live = [SESSION]
    monkeypatch.setattr(state, "desktop_sessions", lambda **kw: live)
    monkeypatch.setattr(state, "rdp_connected", lambda port: False)
    calls = []

    def kill(pid, number):
        calls.append((pid, number))
        live.clear()

    monkeypatch.setattr(state.os, "kill", kill)
    assert state.restart_orphan(SESSION, 3389)
    assert calls == [(42, state.signal.SIGTERM)]


@pytest.mark.parametrize("blocked", ["connected", "recycled", "manager"])
def test_orphan_refusals_never_signal(manager, monkeypatch, blocked):
    monkeypatch.setattr(state, "rdp_connected", lambda port: blocked == "connected")
    monkeypatch.setattr(
        state, "desktop_sessions", lambda **kw: [{**SESSION, "start": "changed"}]
    )
    monkeypatch.setattr(state.os, "kill", lambda *a: pytest.fail("unproved stop"))
    if blocked == "manager":
        (manager / "comm").write_text("other")
    reason = {
        "connected": "orphan_in_use",
        "recycled": "session_changed",
        "manager": "manager_unknown",
    }[blocked]
    with pytest.raises(RuntimeError, match=reason):
        state.restart_orphan(SESSION, 3389)


def test_orphan_stop_timeout_names_sesman_log(manager, monkeypatch):
    monkeypatch.setattr(state, "rdp_connected", lambda port: False)
    monkeypatch.setattr(state, "desktop_sessions", lambda **kw: [SESSION])
    monkeypatch.setattr(state.os, "kill", lambda *a: None)
    ticks = iter([0, 20])
    monkeypatch.setattr(state.time, "monotonic", lambda: next(ticks))
    with pytest.raises(RuntimeError, match="orphan_stop_failed:.*xrdp-sesman.log"):
        state.restart_orphan(SESSION, 3389)


def test_access_restarts_orphan_and_updates_ownership(host, monkeypatch):
    live = [SESSION]
    monkeypatch.setattr(state, "desktop_sessions", lambda **kw: live)

    def restart(session, port):
        assert session == SESSION
        live.clear()
        return True

    monkeypatch.setattr(state, "restart_orphan", restart)
    new_session = {**SESSION, "pid": 43, "start": "400000"}

    def run(*a, **kw):
        assert kw["input"] == PASSWORD + "\n"
        live.append(new_session)
        return subprocess.CompletedProcess([], 0, "ok data=1 display=:10\n", "")

    monkeypatch.setattr(state.subprocess, "run", run)
    assert (
        state.ensure_desktop(PASSWORD, rdp_access=True)["desktop_session"]
        == "restarted"
    )
    assert json.loads(host.read_text())["session"] == new_session
