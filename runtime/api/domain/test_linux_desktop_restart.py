"""Blank-frame recovery protects human desktops and reuses normal startup."""

from io import StringIO
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from yoke_harness.linux_desktop_session import DESKTOP_PROGRAM


@pytest.mark.parametrize("blocked", ["none", "multiple", "human", "password"])
def test_blank_restart_checks_admission_before_stopping(blocked):
    session = {"pid": 42}
    sessions = [] if blocked == "none" else [session]
    if blocked == "multiple":
        sessions.append(session)
    calls = []
    namespace = {
        "sys": SimpleNamespace(
            stdin=StringIO("" if blocked == "password" else "secret\n"),
            argv=["probe", "3389", "0", "1"],
        ),
        "Path": Path,
        "desktop_sessions": lambda: sessions,
        "human_desktop_exists": lambda *a: blocked == "human",
        "stop_desktop": lambda: calls.append("stop"),
        "ensure_desktop": lambda *a, **kw: calls.append("start"),
    }
    with pytest.raises(
        RuntimeError,
        match=(
            "desktop_password_missing"
            if blocked == "password"
            else "linux_desktop_restart_in_use"
        ),
    ):
        exec(DESKTOP_PROGRAM, namespace)
    assert calls == []


def test_blank_restart_stops_then_starts_with_password_on_stdin(capsys):
    calls = []

    def start(password, port, **kwargs):
        calls.append(("start", password, port, kwargs))
        return {"environment": {"DISPLAY": ":11"}, "desktop_session": "started"}

    namespace = {
        "sys": SimpleNamespace(
            stdin=StringIO("secret\n"), argv=["probe", "3390", "0", "1"]
        ),
        "Path": Path,
        "json": json,
        "desktop_sessions": lambda: [{"pid": 42}],
        "human_desktop_exists": lambda *a: False,
        "stop_desktop": lambda: calls.append("stop"),
        "ensure_desktop": start,
    }
    exec(DESKTOP_PROGRAM, namespace)
    assert calls == ["stop", ("start", "secret", 3390, {"rdp_access": False})]
    receipt = json.loads(capsys.readouterr().out)
    assert receipt == {
        "environment": {"DISPLAY": ":11"},
        "desktop_session": "restarted",
    }
