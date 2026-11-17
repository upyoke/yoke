"""GUI transport preserves arguments, host identity, and credential privacy."""

import json
import shlex
import subprocess

import pytest

from yoke_harness import machine_gui_command as gui
from yoke_harness.test_machine_remote_exec import RemoteExecRefusal
from runtime.api.cli.test_browser_authorize_remote import SETTINGS, DECLARATIONS


@pytest.mark.parametrize("kind", ["macos", "linux", "wsl"])
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


@pytest.mark.parametrize("kind", ["macos", "linux", "wsl"])
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
    if kind == "wsl":
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
