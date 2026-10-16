"""Remote authorize opens the desktop viewer and closes it after verification."""

from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

import pytest

from yoke_cli.commands import browser_authorize, browser_authorize_remote as remote
from yoke_harness import test_machine_gui_command as gui
from yoke_harness.desktop_access import DesktopAccessError
from yoke_harness.rdp_desktop_client import CLIENT_RECOVERY

DECLARATIONS = {
    "identities": {
        "buyer": {
            "sites": [
                {
                    "site": "shop",
                    "origin": "https://shop.example.com",
                    "account": "buyer@example.com",
                    "probe": {
                        "url": "https://shop.example.com/me",
                        "signed_in_status": 200,
                    },
                }
            ]
        }
    }
}

RDP = {
    "resource_name": "lab",
    "host": "test.example.com",
    "user": "tester",
    "os": "linux",
    "desktop_route": "ssh-forward",
    "desktop_protocol": "rdp",
    "desktop_port": "3389",
    "desktop_user": "fixture",
}


class Viewer:
    def __init__(self, events, failure=None):
        self.events = events
        self.failure = failure

    def close(self):
        self.events.append("close")
        if self.failure is not None:
            raise DesktopAccessError(self.failure)


@pytest.fixture()
def route(monkeypatch):
    state = {
        "settings": dict(RDP),
        "events": [],
        "result": subprocess.CompletedProcess([], 0, "signed in\n", ""),
    }
    monkeypatch.setattr(
        remote.browser_profile, "profile_project_key", lambda project: "acme"
    )
    monkeypatch.setattr(remote, "ensure_handlers_loaded", lambda: None)
    monkeypatch.setattr(
        remote, "build_actor", lambda: SimpleNamespace(session_id="own")
    )
    monkeypatch.setattr(remote, "read_machine_capability_secret", lambda *args: None)

    def dispatch(**kwargs):
        result = (
            {"machine": "lab", "settings": state["settings"], "active_lease": None}
            if kwargs["function_id"] == "test_machine.get"
            else {"settings_json": json.dumps(DECLARATIONS)}
        )
        return SimpleNamespace(success=True, result=result, error=None)

    def execute(**kwargs):
        state["events"].append("gui")
        return state["result"]

    monkeypatch.setattr(remote, "call_dispatcher", dispatch)
    monkeypatch.setattr(gui, "run_gui_command", execute)
    return state


def authorize(*extra):
    return browser_authorize.browser_authorize(
        ["--project", "acme", "--identity", "buyer", "--machine", "lab", *extra]
    )


def _patch_begin(monkeypatch, route, failure=None):
    def begin(**kwargs):
        route["events"].append("open")
        return Viewer(route["events"], failure)

    monkeypatch.setattr("yoke_harness.desktop_access.begin_desktop_view", begin)


@pytest.mark.parametrize("os_name", ["linux", "windows"])
def test_rdp_route_opens_viewer_for_declared_account_then_closes_it(
    route, monkeypatch, capsys, os_name
):
    route["settings"]["os"] = os_name
    _patch_begin(monkeypatch, route)
    assert authorize() == 0
    assert route["events"] == ["open", "gui", "close"]
    out = capsys.readouterr().out
    assert 'A window titled "Yoke desktop: lab" will appear.' in out
    assert "Sign in with buyer@example.com." in out
    assert "the viewer closes when verification finishes." in out
    assert "signed in" in out


def test_missing_client_prints_view_command_and_still_authorizes(
    route, monkeypatch, capsys
):
    def begin(**kwargs):
        raise DesktopAccessError("desktop_rdp_client_missing: " + CLIENT_RECOVERY)

    monkeypatch.setattr("yoke_harness.desktop_access.begin_desktop_view", begin)
    assert authorize() == 0
    out = capsys.readouterr().out
    assert "desktop_rdp_client_missing" in out
    assert "sdl-freerdp" in out
    assert "yoke test-machine desktop-access --project acme --machine lab --view" in out
    assert route["events"] == ["gui"]


def test_no_desktop_route_prints_command_without_view(route, capsys):
    route["settings"] = {
        "resource_name": "lab",
        "host": "test.example.com",
        "user": "tester",
        "os": "macos",
    }
    assert authorize() == 0
    out = capsys.readouterr().out
    assert "desktop_route_missing" in out
    assert "Run `yoke test-machine desktop-access --project acme --machine lab`." in out
    assert "--view" not in out
    assert "Sign in on its desktop" in out
    assert route["events"] == ["gui"]


def test_vnc_route_prints_desktop_access_without_view(route, capsys):
    route["settings"] = {
        **RDP,
        "os": "macos",
        "desktop_protocol": "vnc",
        "desktop_port": "5900",
    }
    assert authorize() == 0
    out = capsys.readouterr().out
    assert "desktop_view_requires_xfce_rdp" in out
    assert "Run `yoke test-machine desktop-access --project acme --machine lab`." in out
    assert "--view" not in out
    assert route["events"] == ["gui"]


def test_viewer_cleanup_failure_tells_the_operator_and_keeps_success(
    route, monkeypatch, capsys
):
    _patch_begin(
        monkeypatch,
        route,
        failure=(
            "desktop_view_unresponsive: retained log: /tmp/yoke-desktop-view.log; "
            "inspect the log and rerun desktop-access --view"
        ),
    )
    assert authorize() == 0
    err = capsys.readouterr().err
    assert "Close the desktop viewer for machine lab yourself" in err
    assert "desktop_view_unresponsive" in err
    assert route["events"] == ["open", "gui", "close"]


def test_json_mode_keeps_the_receipt_and_still_closes_the_viewer(
    route, monkeypatch, capsys
):
    _patch_begin(monkeypatch, route)
    route["result"] = subprocess.CompletedProcess(
        [], 0, json.dumps({"ok": True, "window_opened": True}), ""
    )
    assert authorize("--json") == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out)["machine"] == "lab"
    assert "Yoke desktop: lab" in captured.err
    assert route["events"] == ["open", "gui", "close"]
