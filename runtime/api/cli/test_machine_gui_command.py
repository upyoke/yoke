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


WSL_COMMAND_LINE_LIMIT = 8 * 1024


def _decoded_wsl_stdin(framed: str) -> tuple[str, str]:
    import base64

    payload, rest = framed.split("\n", 1)
    return base64.b64decode(payload).decode("utf-8"), rest


def test_wsl_desktop_helper_goes_over_stdin_not_the_command_line(
    monkeypatch, tmp_path
):
    from yoke_harness import linux_desktop_session

    seen = []
    receipt = {"desktop_session": "reused", "environment": {"DISPLAY": ":10"}}
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda argv, **kw: (
            seen.append((argv, kw))
            or subprocess.CompletedProcess(argv, 0, json.dumps(receipt), "")
        ),
    )
    control = gui._GuiSshControl({**SETTINGS, "os": "wsl"}, tmp_path, "pw")
    linux_desktop_session.ensure_desktop(control)
    argv, kwargs = seen[0]
    assert len(argv[-1]) < WSL_COMMAND_LINE_LIMIT
    command, stdin = _decoded_wsl_stdin(kwargs["input"])
    assert "def ensure_desktop" in command and stdin == "pw\n"


def test_wsl_streamed_gui_command_goes_over_stdin(monkeypatch, tmp_path, capsys):
    real_popen = subprocess.Popen
    seen = []

    def popen(argv, **kwargs):
        seen.append(argv)
        return real_popen(["cat"], **kwargs)

    monkeypatch.setattr(subprocess, "Popen", popen)
    control = gui._GuiSshControl(
        {**SETTINGS, "os": "wsl"}, tmp_path, None, stream_output=True
    )
    command = shlex.join(["/bin/bash", "-lc", "echo " + "x" * 40_000])
    result = control._run(command, timeout=1920)
    assert control.streamed and result.returncode == 0
    assert len(seen[0][-1]) < WSL_COMMAND_LINE_LIMIT
    assert _decoded_wsl_stdin(result.stdout) == (command, "")


WINDOWS = {**SETTINGS, "resource_name": "windows-native-lab", "os": "windows"}
WINDOWS_FACTS = {
    "os": "Windows", "admin": False, "home": "C:\\Users\\yokeqa",
    "shell": "powershell.exe", "edition": "Windows 11 Pro", "build": "26100",
    "user": "winnative\\yokeqa",
}


def _windows_route(monkeypatch, tmp_path, *, key=True):
    from yoke_contracts.machine_config import capability_secret_store
    from yoke_harness.native_windows import desktop, transport

    key_path = tmp_path / "ssh_private_key"
    if key:
        key_path.write_text("key")
    monkeypatch.setenv("SSH_AUTH_SOCK", "/fake/agent")
    monkeypatch.setattr(
        capability_secret_store, "test_machine_secret_path", lambda name, k: key_path
    )
    monkeypatch.setattr(
        transport.WindowsTransport,
        "_host_facts",
        lambda self: setattr(self, "windows_facts", WINDOWS_FACTS) or WINDOWS_FACTS,
    )
    handed = []
    monkeypatch.setattr(
        desktop,
        "desktop_script",
        lambda control, script, timeout: handed.append((control, script, timeout))
        or subprocess.CompletedProcess([], 0, "signed in", ""),
    )
    return key_path, handed


def test_windows_desktop_runs_through_the_full_native_transport(monkeypatch, tmp_path):
    from yoke_harness.ssh_test_machine_transport import SshTestMachineTransport

    key_path, handed = _windows_route(monkeypatch, tmp_path)
    result = gui.run_gui_command(
        settings=WINDOWS,
        argv=["yoke", "browser", "authorize", "--declarations-json", json.dumps(DECLARATIONS)],
        yoke_home=tmp_path,
    )
    assert result.stdout == "signed in" and result.output_streamed is False
    control, script, timeout = handed[0]
    # Staging reads these through the base transport; the old ssh-agent
    # control had none of them and crashed with AttributeError on `os`.
    assert control.os == "windows" and control.windows_facts["admin"] is False
    assert control.home == "C:\\Users\\yokeqa"
    base = SshTestMachineTransport._ssh_argv(control, "")
    assert base[:3] == ["ssh", "-i", str(key_path)]
    assert base[-2] == "tester@test.example.com"
    assert "$Matches[1]" in script and "browser authorize" in script
    assert timeout == 1920


def test_windows_desktop_without_an_imported_key_refuses_by_name(monkeypatch, tmp_path):
    _, handed = _windows_route(monkeypatch, tmp_path, key=False)
    with pytest.raises(RemoteExecRefusal) as raised:
        gui.run_gui_command(settings=WINDOWS, argv=["yoke", "--version"], yoke_home=tmp_path)
    assert raised.value.code == "desktop_ssh_key_missing"
    assert "yoke test-machine secret set --test-machine windows-native-lab" in raised.value.recovery
    assert handed == []
