"""Desktop commands keep host custody throughout power and sign-in."""

from types import SimpleNamespace
import subprocess

import pytest

from yoke_cli.commands import test_machine_desktop_lease as custody
from yoke_cli.commands import browser_authorize_remote as remote
from yoke_core.domain import cloud_machine_power
from yoke_harness import machine_gui_command as gui
from yoke_harness.test_machine_remote_exec import RemoteExecRefusal
from runtime.api.cli.test_browser_authorize_remote import (
    authorize,
    route as remote_route,
)

route = remote_route


@pytest.mark.parametrize("borrowed", [False, True])
@pytest.mark.parametrize("failure", [None, "power", "desktop"])
def test_lease_survives_power_and_desktop_and_only_owned_hold_releases(
    monkeypatch, borrowed, failure
):
    events = []
    lease = {"id": 12, "session_id": "own"} if borrowed else None

    def dispatch(**kw):
        name = kw["function_id"]
        events.append(name)
        return SimpleNamespace(success=True, result={"claim": {"id": 12}}, error=None)

    def power(*args):
        events.append("power")
        if failure == "power":
            raise RuntimeError("cloud unavailable")

    monkeypatch.setattr(custody, "call_dispatcher", dispatch)
    monkeypatch.setattr(cloud_machine_power, "power_on", power)
    try:
        with custody.desktop_lease(
            project="acme",
            test_machine="lab",
            settings={"cloud_instance_id": "stopped"},
            actor=SimpleNamespace(session_id="own"),
            detail={"active_lease": lease},
        ):
            events.append("desktop")
            if failure == "desktop":
                raise RuntimeError("viewer failed")
    except RuntimeError:
        assert failure
    expected = ["power"] + ([] if failure == "power" else ["desktop"])
    if not borrowed:
        expected = [
            "claims.coordination_claim.acquire_if_free",
            *expected,
            "claims.coordination_claim.release",
        ]
    assert events == expected


def test_foreign_holder_refuses_without_power(monkeypatch):
    monkeypatch.setattr(
        cloud_machine_power, "power_on", lambda *a: pytest.fail("powered")
    )
    with pytest.raises(RuntimeError, match="test_machine_leased"):
        with custody.desktop_lease(
            project="acme",
            test_machine="lab",
            settings={},
            actor=SimpleNamespace(session_id="own"),
            detail={"active_lease": {"id": 12, "session_id": "other"}},
        ):
            pytest.fail("desktop opened")


def test_steering_assistance_leaves_foreign_lease_unchanged(monkeypatch):
    monkeypatch.setattr(
        custody, "call_dispatcher", lambda **kw: pytest.fail("lease changed")
    )
    monkeypatch.setattr(cloud_machine_power, "power_on", lambda *a: None)
    with custody.desktop_lease(
        project="acme",
        test_machine="lab",
        settings={},
        actor=SimpleNamespace(session_id="own"),
        operator_access={"lease_id": 12},
    ):
        pass


def test_authorize_powers_before_precheck_and_viewer_and_releases_after_sign_in(
    route, monkeypatch
):
    events = []
    monkeypatch.setattr(
        cloud_machine_power, "power_on", lambda *a: events.append("power")
    )
    monkeypatch.setattr(
        gui, "check_yoke_installation", lambda **kw: events.append("installed")
    )
    viewer = SimpleNamespace(close=lambda: events.append("closed"))
    monkeypatch.setattr(
        remote, "_open_sign_in_viewer", lambda *a: events.append("viewer") or viewer
    )

    def run(**kw):
        events.append("sign-in")
        assert (
            route["calls"][-1]["function_id"]
            == "claims.coordination_claim.acquire_if_free"
        )
        return route["result"]

    monkeypatch.setattr(gui, "run_gui_command", run)
    assert authorize("--json") == 0
    assert events == ["power", "installed", "viewer", "sign-in", "closed"]
    assert route["calls"][-1]["function_id"] == "claims.coordination_claim.release"


def test_fresh_host_refuses_before_viewer_and_releases_lease(
    route, monkeypatch, capsys
):
    def missing(**kw):
        raise RemoteExecRefusal(
            "test_machine_yoke_missing",
            "Yoke missing",
            "reset --baseline shell-preconfigured",
        )

    monkeypatch.setattr(gui, "check_yoke_installation", missing)
    monkeypatch.setattr(
        remote, "_open_sign_in_viewer", lambda *a: pytest.fail("viewer opened")
    )
    assert authorize("--json") == 2
    assert "test_machine_yoke_missing" in capsys.readouterr().out
    assert not route["argv"]
    assert route["calls"][-1]["function_id"] == "claims.coordination_claim.release"


@pytest.mark.parametrize("kind", ["linux", "wsl", "macos"])
def test_installed_yoke_probe_uses_login_shell_without_desktop(
    monkeypatch, tmp_path, kind
):
    commands = []
    monkeypatch.setattr(
        gui._GuiSshControl,
        "_run",
        lambda self, command, **kw: (
            commands.append(command) or subprocess.CompletedProcess([], 1, "", "")
        ),
    )
    with pytest.raises(RemoteExecRefusal, match="Yoke is absent") as caught:
        gui.check_yoke_installation(
            project="acme",
            test_machine="lab",
            settings={"os": kind},
            yoke_home=tmp_path,
        )
    assert commands == ["/bin/bash -lc 'command -v yoke'"]
    assert caught.value.code == "test_machine_yoke_missing"
    assert (
        "yoke test-machine reset --project acme --test-machine lab --baseline shell-preconfigured"
        in caught.value.recovery
    )


@pytest.mark.parametrize("fails", [False, True])
def test_desktop_access_holds_lease_until_view_returns(monkeypatch, capsys, fails):
    from yoke_cli.commands.adapters import test_machine_desktop as cli
    from yoke_harness import desktop_access

    events = []
    route = {"project": "acme", "test_machine": "lab", "settings": {}}
    monkeypatch.setattr(cli, "ensure_handlers_loaded", lambda: None)
    monkeypatch.setattr(
        cli, "build_actor", lambda **kw: SimpleNamespace(session_id="own")
    )

    def dispatch(**kw):
        function = kw["function_id"]
        events.append(function)
        result = (
            route
            if function == "test_machine.desktop_access"
            else (
                {"active_lease": None}
                if function == "test_machine.get"
                else {"claim": {"id": 12}}
            )
        )
        return SimpleNamespace(success=True, result=result, error=None)

    def view(**kw):
        assert events[-1] == "power"
        assert kw["view"] is True
        events.append("desktop")
        if fails:
            raise desktop_access.DesktopAccessError(
                "desktop_unreachable: repair the route"
            )
        return {"viewer": "closed"}

    monkeypatch.setattr(cli, "call_dispatcher", dispatch)
    monkeypatch.setattr(custody, "call_dispatcher", dispatch)
    monkeypatch.setattr(
        cloud_machine_power, "power_on", lambda *a: events.append("power")
    )
    monkeypatch.setattr(desktop_access, "open_desktop_access", view)
    assert cli.test_machine_desktop_access(
        ["--project", "acme", "--test-machine", "lab", "--view"]
    ) == int(fails)
    assert events == [
        "test_machine.desktop_access",
        "test_machine.get",
        "claims.coordination_claim.acquire_if_free",
        "power",
        "desktop",
        "claims.coordination_claim.release",
    ]
