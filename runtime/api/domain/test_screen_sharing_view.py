"""Screen Sharing views a Mac test machine without the password in argv or URL."""

from contextlib import contextmanager
import io
import subprocess

import pytest

from yoke_contracts.machine_config.capability_secret_store import store_machine_capability_secret
from yoke_harness import desktop_access, desktop_forward, screen_sharing_view as sharing

PASSWORD = "fixture-secret"
SETTINGS = {
    "resource_name": "test-mac",
    "os": "macos",
    "host": "mac.example",
    "user": "admin",
    "desktop_route": "direct",
    "desktop_protocol": "vnc",
    "desktop_port": "5900",
    "desktop_user": "oxpecker",
}


class Workstation:
    """Records open/pbcopy/pbpaste calls against one fake clipboard."""

    def __init__(self, open_code=0):
        self.clipboard = ""
        self.calls = []
        self.open_code = open_code

    def run(self, argv, **kwargs):
        self.calls.append((argv, kwargs.get("input")))
        if argv[0] == "pbcopy":
            self.clipboard = kwargs["input"]
            return subprocess.CompletedProcess(argv, 0, "", "")
        if argv[0] == "pbpaste":
            return subprocess.CompletedProcess(argv, 0, self.clipboard, "")
        return subprocess.CompletedProcess(argv, self.open_code, b"", b"")


@pytest.fixture()
def mac(monkeypatch):
    events = []
    station = Workstation()
    monkeypatch.setattr(sharing.sys, "platform", "darwin")
    monkeypatch.setattr(sharing.subprocess, "run", station.run)

    @contextmanager
    def forward(project, settings):
        events.append("forward-open")
        try:
            yield "127.0.0.1", 5555, "oxpecker"
        finally:
            events.append("forward-close")

    monkeypatch.setattr(sharing, "desktop_forward", forward)
    return station, events


def test_open_keeps_password_out_of_argv_and_url(mac, capsys):
    station, events = mac
    view = sharing.ScreenSharingView.open("project", "test-mac", SETTINGS, PASSWORD)
    try:
        assert view.address == "vnc://oxpecker@127.0.0.1:5555"
        assert ["open", view.address] in [argv for argv, _ in station.calls]
        assert ("pbcopy", PASSWORD) in [(argv[0], data) for argv, data in station.calls]
        assert all(PASSWORD not in repr(argv) for argv, _ in station.calls)
        err = capsys.readouterr().err
        assert "Paste the desktop password from the clipboard" in err
        assert "Clipboard-history apps" in err
        assert PASSWORD not in err
        assert events == ["forward-open"]
    finally:
        view.close()
    assert events == ["forward-open", "forward-close"]
    assert station.clipboard == ""


def test_clipboard_clears_only_while_it_holds_the_password(mac):
    station, _ = mac
    view = sharing.ScreenSharingView.open("project", "test-mac", SETTINGS, PASSWORD)
    station.clipboard = "operator copy"
    view.close()
    assert station.clipboard == "operator copy"


def test_expiry_clears_the_password_once(mac):
    station, _ = mac
    view = sharing.ScreenSharingView.open("project", "test-mac", SETTINGS, PASSWORD)
    view._timer.cancel()
    view._expire()
    assert station.clipboard == ""
    station.clipboard = PASSWORD
    view.close()
    # Yoke cleared its copy already; a later identical copy is the operator's.
    assert station.clipboard == PASSWORD


def test_open_failure_clears_clipboard_and_closes_forward(mac):
    station, events = mac
    station.open_code = 1
    with pytest.raises(desktop_access.DesktopAccessError, match="desktop_view_open_failed"):
        sharing.ScreenSharingView.open("project", "test-mac", SETTINGS, PASSWORD)
    assert station.clipboard == ""
    assert events == ["forward-open", "forward-close"]


def test_non_mac_workstation_refuses_with_recovery(monkeypatch):
    monkeypatch.setattr(sharing.sys, "platform", "linux")
    monkeypatch.setattr(
        sharing, "desktop_forward", lambda *a: pytest.fail("forward opened")
    )
    with pytest.raises(desktop_access.DesktopAccessError) as refused:
        sharing.ScreenSharingView.open("project", "test-mac", SETTINGS, PASSWORD)
    assert "desktop_view_requires_mac_workstation" in str(refused.value)
    assert "without --view" in str(refused.value)
    assert "VNC client" in str(refused.value)


def test_enter_closes_the_route(mac, monkeypatch):
    station, events = mac
    monkeypatch.setattr(sharing.sys, "stdin", io.StringIO("\n"))
    result = sharing.view_screen_sharing("project", "test-mac", SETTINGS, PASSWORD)
    assert result == {
        "address": "vnc://oxpecker@127.0.0.1:5555",
        "user": "oxpecker",
        "viewer": "closed",
    }
    assert events[-1] == "forward-close"
    assert station.clipboard == ""


def test_no_terminal_holds_the_route_until_the_clipboard_clears(mac, monkeypatch):
    station, events = mac
    monkeypatch.setattr(sharing, "CLIPBOARD_SECONDS", 0.01)
    monkeypatch.setattr(sharing.sys, "stdin", io.StringIO(""))
    sharing.view_screen_sharing("project", "test-mac", SETTINGS, PASSWORD)
    assert [argv[0] for argv, _ in station.calls][-2:] == ["pbpaste", "pbcopy"]
    assert events[-1] == "forward-close"


def test_desktop_access_view_routes_macos_vnc_to_screen_sharing(tmp_path, monkeypatch):
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine"))
    store_machine_capability_secret(
        "project", "test-machine:test-mac", "desktop_password", PASSWORD
    )
    monkeypatch.setattr(
        desktop_access, "_prepare_desktop", lambda *a: pytest.fail("XFCE prepared")
    )
    calls = []
    monkeypatch.setattr(
        sharing, "view_screen_sharing", lambda *a: calls.append(a) or {"viewer": "closed"}
    )
    assert desktop_access.open_desktop_access(
        project="project", test_machine="test-mac", settings=SETTINGS, view=True
    ) == {"viewer": "closed"}
    assert calls[0][3] == PASSWORD


@pytest.mark.parametrize(
    "settings",
    [{**SETTINGS, "os": "linux"}, {**SETTINGS, "desktop_protocol": "rdp"}],
)
def test_other_view_routes_refuse_with_recovery(settings):
    with pytest.raises(
        desktop_access.DesktopAccessError, match="desktop_view_route_unsupported"
    ) as refused:
        desktop_access.begin_desktop_view(
            project="project", test_machine="test-mac", settings=settings
        )
    assert "without --view" in str(refused.value)


def test_forward_checks_the_declared_vnc_handshake(monkeypatch):
    checked = []
    monkeypatch.setattr(
        desktop_access, "_check_desktop", lambda *a: checked.append(a)
    )
    with desktop_forward.desktop_forward("project", SETTINGS) as route:
        assert route == ("mac.example", 5900, "oxpecker")
    assert checked == [("mac.example", 5900, "vnc")]
