"""Desktop access announces a usable route and holds only the SSH-forward fallback."""

from __future__ import annotations

import io
import json
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace

import pytest

from yoke_contracts.machine_config.capability_secret_store import (
    store_test_machine_secret,
)
from yoke_contracts.owner_private_path import is_owner_private_file
from yoke_harness import desktop_access as desktop

from runtime.api.domain.test_machine_desktop_access import PASSWORD, SETTINGS


pytestmark = pytest.mark.windows


@pytest.fixture
def credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine"))
    store_test_machine_secret("lab", "ssh_private_key", "fake-key")
    store_test_machine_secret("lab", "desktop_password", PASSWORD)
    return tmp_path


@pytest.fixture
def forward(monkeypatch):
    """Stand in for desktop_forward, whose own tests own the SSH child."""
    from contextlib import contextmanager
    from yoke_harness import desktop_forward as module

    state = {"open": False, "opened": 0, "fail": None}

    @contextmanager
    def fake(project, settings):
        if state["fail"]:
            raise state["fail"]
        route = settings["desktop_route"]
        host = "127.0.0.1" if route == "ssh-forward" else settings.get("desktop_host") or settings["host"]
        state["open"] = True
        state["opened"] += 1
        try:
            yield host, 49152 if route == "ssh-forward" else int(settings["desktop_port"]), settings["desktop_user"]
        finally:
            state["open"] = False

    monkeypatch.setattr(module, "desktop_forward", fake)
    return state


def _open(settings=SETTINGS, test_machine="lab"):
    announced = []
    desktop.open_desktop_access(
        project="project", test_machine=test_machine, settings=settings, announce=announced.append
    )
    return announced


def test_ssh_forward_announces_a_private_copy_then_holds_the_forward(
    credentials, forward, monkeypatch
):
    held = []
    monkeypatch.setattr(desktop, "_hold_forward", lambda: held.append(forward["open"]))
    [result] = _open()
    path = Path(result["password_file"])
    try:
        assert held == [True] and forward["open"] is False
        assert set(result) == {"address", "route", "user", "password_file"}
        assert result["address"] == "rdp://127.0.0.1:49152"
        assert result["route"] == "ssh-forward"
        assert PASSWORD not in json.dumps(result)
        assert path.parent == Path(tempfile.gettempdir())
        assert path.read_text().strip() == PASSWORD
        assert is_owner_private_file(path)
    finally:
        path.unlink()


def test_direct_route_announces_and_returns_without_holding(credentials, forward, monkeypatch):
    monkeypatch.setattr(desktop, "_hold_forward", lambda: pytest.fail("direct route holds"))
    settings = {**SETTINGS, "desktop_route": "direct", "desktop_protocol": "vnc"}
    [result] = _open({**settings, "desktop_host": "desktop.example", "desktop_port": "5900"})
    try:
        assert result["address"] == "vnc://desktop.example:5900"
        assert "certificate_sha256" not in result
    finally:
        Path(result["password_file"]).unlink()


def test_direct_rdp_announces_its_pinned_certificate(credentials, forward, monkeypatch):
    from yoke_harness import rdp_certificate_pin

    pins = []
    monkeypatch.setattr(
        rdp_certificate_pin,
        "pinned_certificate",
        lambda host, port, error, yoke_home: pins.append((host, port)) or "ab" * 32,
    )
    monkeypatch.setattr(desktop, "_hold_forward", lambda: pytest.fail("direct route holds"))
    [result] = _open({**SETTINGS, "desktop_route": "direct", "host": "lab.tail.ts.net"})
    try:
        assert pins == [("lab.tail.ts.net", 3389)]
        assert result["address"] == "rdp://lab.tail.ts.net:3389"
        assert result["certificate_sha256"] == "ab" * 32
    finally:
        Path(result["password_file"]).unlink()


def test_failed_route_announces_nothing_and_leaves_no_password_copy(
    credentials, forward, monkeypatch
):
    monkeypatch.setattr(
        desktop.tempfile, "mkstemp", lambda **kw: pytest.fail("password copy created")
    )
    forward["fail"] = desktop.DesktopAccessError("desktop_unreachable: check the route")
    with pytest.raises(desktop.DesktopAccessError, match="desktop_unreachable"):
        _open()


def test_missing_password_refuses_before_any_forward(credentials, forward):
    with pytest.raises(desktop.DesktopAccessError, match="desktop_password_missing"):
        _open(test_machine="missing")
    assert forward["opened"] == 0


@pytest.mark.parametrize("line", ["\n", ""])
def test_hold_ends_on_enter_or_an_interrupt_without_a_terminal(monkeypatch, line):
    monkeypatch.setattr(sys, "stdin", io.StringIO(line))
    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        raise KeyboardInterrupt

    monkeypatch.setattr(time, "sleep", sleep)
    desktop._hold_forward()
    assert sleeps == ([] if line else [1])


def test_cli_dispatch_never_contains_a_password(credentials, forward, monkeypatch, capsys):
    from yoke_cli.commands.adapters import test_machine_desktop as cli

    calls = []
    monkeypatch.setattr(cli, "ensure_handlers_loaded", lambda: None)
    monkeypatch.setattr(
        cli, "build_actor", lambda **kw: SimpleNamespace(session_id="caller")
    )
    monkeypatch.setattr(
        cli,
        "call_dispatcher",
        lambda **kw: (
            calls.append(kw)
            or SimpleNamespace(
                success=True,
                result={"project": "project", "test_machine": "lab", "settings": SETTINGS},
            )
        ),
    )
    from contextlib import nullcontext
    from yoke_cli.commands import test_machine_desktop_lease as custody

    monkeypatch.setattr(custody, "desktop_lease", lambda **kw: nullcontext())
    monkeypatch.setattr(desktop, "_hold_forward", lambda: None)
    assert (
        cli.test_machine_desktop_access(["--test-machine", "lab"])
        == 0
    )
    captured = capsys.readouterr()
    result = json.loads(captured.out)
    try:
        assert calls[0]["payload"] == {"test_machine": "lab"}
        assert PASSWORD not in captured.out + captured.err + repr(calls)
    finally:
        Path(result["password_file"]).unlink()




WINDOWS = {
    **SETTINGS,
    "os": "windows",
    "desktop_route": "direct",
    "host": "lab.tail.ts.net",
    "desktop_user": "yokeqa",
}


def test_native_windows_view_opens_the_native_viewer(credentials, monkeypatch):
    from yoke_harness import native_windows_desktop_view as native

    calls = []
    monkeypatch.setattr(
        native,
        "view_native_desktop",
        lambda *a: calls.append(a) or {"desktop_session": "native", "viewer": "closed"},
    )
    monkeypatch.setattr(
        desktop, "_prepare_desktop", lambda *a: pytest.fail("SSH desktop run")
    )
    announced = []
    desktop.open_desktop_access(
        project="project",
        test_machine="lab",
        settings=WINDOWS,
        announce=announced.append,
        view=True,
    )
    assert announced == [{"desktop_session": "native", "viewer": "closed"}]
    assert calls == [("project", "lab", WINDOWS, PASSWORD)]


def test_native_windows_plain_access_is_unchanged(credentials, forward, monkeypatch):
    from yoke_harness import rdp_certificate_pin

    monkeypatch.setattr(
        rdp_certificate_pin, "pinned_certificate", lambda *a, **kw: "cd" * 32
    )
    monkeypatch.setattr(
        desktop, "_prepare_desktop", lambda *a: pytest.fail("SSH desktop run")
    )
    monkeypatch.setattr(desktop, "_hold_forward", lambda: pytest.fail("direct route holds"))
    [result] = _open(WINDOWS)
    try:
        assert set(result) == {
            "address", "route", "user", "password_file", "certificate_sha256"
        }
        assert result["address"] == "rdp://lab.tail.ts.net:3389"
        assert result["user"] == "yokeqa"
    finally:
        Path(result["password_file"]).unlink()


def test_view_refuses_an_unviewable_route_by_name(credentials):
    with pytest.raises(desktop.DesktopAccessError) as refused:
        desktop.open_desktop_access(
            project="project",
            test_machine="lab",
            settings={**WINDOWS, "desktop_protocol": "vnc", "desktop_port": "5900"},
            announce=lambda result: pytest.fail("announced"),
            view=True,
        )
    assert "desktop_view_route_unsupported" in str(refused.value)
    assert "windows_desktop_view_requires_rdp" not in str(refused.value)
