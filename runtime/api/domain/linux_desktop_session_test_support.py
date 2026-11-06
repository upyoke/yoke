# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

import json

import shlex

import subprocess

from types import SimpleNamespace

import pytest

from yoke_harness import linux_desktop_state as state

from yoke_harness.linux_desktop_session import desktop_command

from yoke_harness.ssh_linux_reset_preconditions import DESKTOP_PROGRAM

PASSWORD = "desktop-secret-with-$()-and-quotes"

SESSION = {
    "pid": 42,
    "start": "123456",
    "session_id": "c2",
    "environment": {
        "DISPLAY": ":10",
        "GDK_BACKEND": "x11",
        "XAUTHORITY": "/home/test/.Xauthority",
        "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus",
    },
}


@pytest.fixture
def host(tmp_path, monkeypatch):
    marker = tmp_path / "ownership.json"
    marker.touch(mode=0o600)

    def ownership():
        return marker.open("r+")

    monkeypatch.setattr(state, "ownership_file", ownership)
    monkeypatch.setattr(state, "graphical_sessions", lambda **kw: [])
    monkeypatch.setattr(state, "human_desktop_exists", lambda *a: False)
    monkeypatch.setattr(state, "rdp_connected", lambda *a: False)
    monkeypatch.setattr(state, "desktop_sessions", lambda **kw: [])
    return marker
