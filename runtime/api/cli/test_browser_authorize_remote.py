"""Remote sign-in uses declared settings, lease ownership and real GUI helpers."""

from __future__ import annotations

import json
import shlex
import subprocess
from types import SimpleNamespace

import pytest

from yoke_cli.commands import browser_authorize, browser_authorize_remote as remote
from yoke_harness import test_machine_gui_command as gui
from yoke_harness.test_machine_remote_exec import RemoteExecRefusal


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
    monkeypatch.setattr(remote, "read_machine_capability_secret", lambda *args: None)

    def dispatch(**kwargs):
        state["calls"].append(kwargs)
        result = (
            {
                "machine": "test-mac",
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


def test_desktop_only_and_omitted_identity_are_resolved_before_viewer(route, capsys):
    assert authorize("--desktop-browser", "--json") == 0
    argv = route["argv"][0]["argv"]
    assert "--desktop-browser" in argv and "--include-desktop-browser" not in argv
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
    assert json.loads(capsys.readouterr().out)["machine"] == "test-mac"


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


@pytest.mark.parametrize("kind", ["macos", "linux", "windows"])
def test_os_gui_route_preserves_argv_and_uses_existing_helper(
    monkeypatch, tmp_path, kind
):
    from yoke_harness import linux_desktop_session, ssh_mac_gui_session

    calls = []
    sentinel = subprocess.CompletedProcess([], 0, "signed in", "")
    monkeypatch.setenv("SSH_AUTH_SOCK", "/fake/agent")
    monkeypatch.setattr(
        ssh_mac_gui_session,
        "run_terminal_app_command",
        lambda run, **kw: calls.append((run, kw)) or sentinel,
    )
    monkeypatch.setattr(
        linux_desktop_session,
        "desktop_command",
        lambda control, argv, **kw: (
            calls.append((control, {"argv": argv, **kw})) or sentinel
        ),
    )
    argv = [
        "yoke",
        "browser",
        "authorize",
        "--declarations-json",
        json.dumps(DECLARATIONS),
    ]
    assert (
        gui.run_gui_command(
            settings={**SETTINGS, "os": kind}, argv=argv, yoke_home=tmp_path
        )
        is sentinel
    )
    expected = argv if kind == "macos" else ["/bin/bash", "-lc", shlex.join(argv)]
    assert calls[0][1] == {"argv": expected, "timeout": 1920}


def test_ssh_agent_is_required(monkeypatch, tmp_path):
    monkeypatch.delenv("SSH_AUTH_SOCK", raising=False)
    with pytest.raises(RemoteExecRefusal, match="SSH_AUTH_SOCK"):
        gui.run_gui_command(settings=SETTINGS, argv=["yoke"], yoke_home=tmp_path)


@pytest.mark.parametrize("kind", ["macos", "linux", "windows"])
def test_gui_transport_quotes_commands_and_pins_ssh_keys(monkeypatch, tmp_path, kind):
    seen = []
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda argv, **kw: (
            seen.append((argv, kw))
            or subprocess.CompletedProcess(argv, 0, "secret", "secret")
        ),
    )
    control = gui._GuiSshControl({**SETTINGS, "os": kind}, tmp_path, "secret")
    command = shlex.join(
        [
            "yoke",
            "browser",
            "authorize",
            "--declarations-json",
            json.dumps(DECLARATIONS),
        ]
    )
    result = control._run(command, timeout=10)
    assert result.stdout == result.stderr == "[REDACTED]"
    assert "-F" in seen[0][0] and "IdentityFile=none" in seen[0][0]
    assert "StrictHostKeyChecking=accept-new" in seen[0][0]
    assert seen[0][1]["timeout"] == 10
    if kind == "windows":
        assert seen[0][0][-1].startswith("powershell.exe ")
    else:
        assert seen[0][0][-1] == command


@pytest.mark.parametrize(
    "failure,error",
    [
        ("timeout", "test_machine_gui_command_timeout"),
        ("ssh", "test_machine_ssh_failed"),
        ("missing", "test_machine_ssh_unavailable"),
    ],
)
def test_transport_failures_name_reason_and_recovery(
    monkeypatch, tmp_path, failure, error
):
    def run(argv, **kwargs):
        if failure == "timeout":
            raise subprocess.TimeoutExpired(argv, 10)
        if failure == "missing":
            raise FileNotFoundError("ssh")
        return subprocess.CompletedProcess(argv, 255, "", "connection refused")

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(RemoteExecRefusal) as raised:
        gui._GuiSshControl(SETTINGS, tmp_path, None)._run("true", timeout=10)
    assert raised.value.code == error and raised.value.recovery


def test_no_browser_capability_still_has_default_identity(route, monkeypatch, capsys):
    original = remote.call_dispatcher

    def dispatch(**kwargs):
        if kwargs["function_id"] == "projects.capability_settings.get":
            return SimpleNamespace(
                success=False, result=None, error=SimpleNamespace(code="not_found")
            )
        return original(**kwargs)

    monkeypatch.setattr(remote, "call_dispatcher", dispatch)
    assert authorize("--identity", "default", "--json") == 0
    argv = route["argv"][0]["argv"]
    assert json.loads(argv[argv.index("--declarations-json") + 1]) == {}
    assert json.loads(capsys.readouterr().out)["ok"] is True
