"""Remote sign-in uses declared settings, lease ownership and real GUI helpers."""

from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

import pytest

from yoke_cli.commands import browser_authorize, browser_authorize_remote as remote
from yoke_harness import machine_gui_command as gui

SETTINGS = {
    "resource_name": "test-mac",
    "host": "test.example.com",
    "user": "tester",
    "os": "macos",
    "operating_notes": "Dedicated desktop",
}
DECLARATIONS = {
    "identities": {
        "buyer": {
            "sites": [
                {
                    "site": "shop",
                    "origin": "https://shop.example.com",
                    "account": "a'b@example.com",
                    "probe": {
                        "url": "https://shop.example.com/me",
                        "signed_in_status": 200,
                    },
                }
            ]
        }
    }
}


@pytest.fixture()
def route(monkeypatch, tmp_path):
    state = {
        "lease": None,
        "declarations": json.dumps(DECLARATIONS),
        "calls": [],
        "argv": [],
        "result": subprocess.CompletedProcess(
            [], 0, json.dumps({"ok": True, "window_opened": True}), ""
        ),
    }
    monkeypatch.setattr(
        remote.browser_profile, "profile_project_key", lambda project: "acme"
    )
    monkeypatch.setattr(remote.machine_config, "yoke_home", lambda: tmp_path)
    monkeypatch.setattr(remote, "ensure_handlers_loaded", lambda: None)
    monkeypatch.setattr(
        remote, "build_actor", lambda: SimpleNamespace(session_id="own")
    )
    monkeypatch.setattr(remote, "read_test_machine_secret", lambda *args: None)

    def dispatch(**kwargs):
        state["calls"].append(kwargs)
        if kwargs["function_id"] in {"test_machine.lease_acquire", "claims.coordination_claim.release"}:
            return SimpleNamespace(
                success=True, result={"claim_id": 42}, error=None
            )
        result = (
            {
                "test_machine": "test-mac",
                "settings": SETTINGS,
                "active_lease": state["lease"],
            }
            if kwargs["function_id"] == "test_machine.get"
            else {"settings_json": state["declarations"]}
        )
        return SimpleNamespace(success=True, result=result, error=None)

    def execute(**kwargs):
        state["argv"].append(kwargs)
        return state["result"]

    from yoke_cli.commands import test_machine_desktop_lease as custody
    from yoke_core.domain import cloud_machine_power

    monkeypatch.setattr(custody, "call_dispatcher", dispatch)
    monkeypatch.setattr(cloud_machine_power, "power_on", lambda *a: None)
    monkeypatch.setattr(gui, "check_yoke_installation", lambda **kw: None)
    monkeypatch.setattr(remote, "call_dispatcher", dispatch)
    monkeypatch.setattr(gui, "run_gui_command", execute)
    return state


def authorize(*extra):
    return browser_authorize.browser_authorize(
        [
            "--project",
            "acme",
            "--identity",
            "buyer",
            "--test-machine",
            "test-mac",
            *extra,
        ]
    )


def test_identity_only_and_omitted_identity_are_resolved_before_viewer(route, capsys):
    assert authorize("--json") == 0
    argv = route["argv"][0]["argv"]
    assert not any("desktop-browser" in part for part in argv)
    assert "https://shop.example.com" in capsys.readouterr().err
    route["argv"].clear()
    assert (
        browser_authorize.browser_authorize(
            ["--project", "acme", "--test-machine", "test-mac", "--json"]
        )
        == 2
    )
    assert "browser_identity_required" in json.loads(capsys.readouterr().out)["error"]
    assert not route["argv"]


def test_remote_reads_settings_and_forwards_options_without_local_browser(
    route, monkeypatch, capsys
):
    monkeypatch.setattr(
        browser_authorize,
        "prepare_browser_runtime",
        lambda *a: pytest.fail("local browser started"),
    )
    assert (
        authorize("--json", "--reset", "--url", "https://shop.example.com/?q='x'") == 0
    )
    assert [c["function_id"] for c in route["calls"]] == [
        "test_machine.get",
        "projects.capability_settings.get",
        "test_machine.lease_acquire",
        "claims.coordination_claim.release",
        "test_machine.get",
    ]
    argv = route["argv"][0]["argv"]
    assert argv[:7] == [
        "yoke",
        "browser",
        "authorize",
        "--project",
        "acme",
        "--identity",
        "buyer",
    ]
    assert json.loads(argv[argv.index("--declarations-json") + 1]) == DECLARATIONS
    assert "--test-machine" not in argv and "--reset" in argv and "--json" in argv
    assert argv[argv.index("--url") + 1] == "https://shop.example.com/?q='x'"
    assert json.loads(capsys.readouterr().out)["test_machine"] == "test-mac"


@pytest.mark.parametrize("lease", [None, {"session_id": "own"}])
def test_unleased_or_owned_machine_can_authorize(route, lease, capsys):
    route["lease"] = lease
    route["result"] = subprocess.CompletedProcess([], 0, "Profile saved\n", "")
    assert authorize() == 0
    assert "Sign in on its desktop" in capsys.readouterr().out


def test_other_session_lease_refuses_before_browser_or_settings_read(route, capsys):
    route["lease"] = {"session_id": "other"}
    assert authorize("--json") == 2
    assert len(route["calls"]) == 1 and route["argv"] == []
    assert "test_machine_leased" in json.loads(capsys.readouterr().out)["error"]


@pytest.mark.parametrize(
    "extra,error",
    [
        (
            ["--declarations-json", "{}"],
            "browser_authorize_machine_declarations_conflict",
        ),
        (["--identity", "admin"], "browser_identity_undeclared"),
    ],
)
def test_bad_identity_or_conflicting_declarations_never_execute(
    route, extra, error, capsys
):
    assert authorize("--json", *extra) == 2
    assert error in json.loads(capsys.readouterr().out)["error"]
    assert not route["argv"]


@pytest.mark.parametrize("declarations", ["broken", "[]"])
def test_unreadable_settings_are_diagnosed(route, declarations, capsys):
    route["declarations"] = declarations
    assert authorize("--json") == 2
    assert (
        "browser_identity_declarations_unreadable"
        in json.loads(capsys.readouterr().out)["error"]
    )
    assert not route["argv"]


def test_remote_sign_out_is_not_reported_as_success(route, capsys):
    route["result"] = subprocess.CompletedProcess(
        [], 1, json.dumps({"ok": False, "error": "browser_sign_in_incomplete"}), ""
    )
    assert authorize("--json") == 1
    assert json.loads(capsys.readouterr().out)["ok"] is False


@pytest.mark.parametrize(
    "code,stdout", [(0, ""), (0, "[]"), (1, '{"ok":true}'), (0, '{"ok":false}')]
)
def test_missing_or_inconsistent_receipt_refuses(route, code, stdout, capsys):
    route["result"] = subprocess.CompletedProcess([], code, stdout, "GUI failure")
    assert authorize("--json") == 2
    assert (
        "browser_authorize_remote_receipt_invalid"
        in json.loads(capsys.readouterr().out)["error"]
    )


def test_control_plane_refusal_keeps_named_recovery(route, monkeypatch, capsys):
    monkeypatch.setattr(
        remote,
        "call_dispatcher",
        lambda **kwargs: SimpleNamespace(
            success=False,
            result=None,
            error=SimpleNamespace(
                code="not_found",
                message="machine not registered",
                recovery_hint="Register the machine.",
            ),
        ),
    )
    assert authorize("--json") == 2
    assert "Register the machine." in json.loads(capsys.readouterr().out)["error"]
    assert not route["argv"]


def test_no_browser_capability_still_has_default_identity(route, monkeypatch, capsys):
    original = remote.call_dispatcher

    def dispatch(**kwargs):
        if kwargs["function_id"] == "projects.capability_settings.get":
            return SimpleNamespace(
                success=False, result=None, error=SimpleNamespace(code="not_found")
            )
        return original(**kwargs)

    from yoke_cli.commands import test_machine_desktop_lease as custody
    from yoke_core.domain import cloud_machine_power

    monkeypatch.setattr(custody, "call_dispatcher", dispatch)
    monkeypatch.setattr(cloud_machine_power, "power_on", lambda *a: None)
    monkeypatch.setattr(gui, "check_yoke_installation", lambda **kw: None)
    monkeypatch.setattr(remote, "call_dispatcher", dispatch)
    assert authorize("--identity", "default", "--json") == 0
    argv = route["argv"][0]["argv"]
    assert json.loads(argv[argv.index("--declarations-json") + 1]) == {}
    assert json.loads(capsys.readouterr().out)["ok"] is True
