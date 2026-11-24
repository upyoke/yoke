"""Windows transport reaches Linux operations without interpreting Linux argv."""

from __future__ import annotations

import base64
import json
import re
import shlex
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from yoke_contracts.machine_config.test_machine import (
    validate_test_machine_settings,
)
from yoke_contracts.machine_qa_failures import HostControlLocalError
from yoke_core.domain.host_baseline_operations import run_host_baseline
from yoke_core.domain.machine_qa_host_control import host_control_for
from yoke_core.domain.ssh_windows_host_control import SshWindowsHostControl
from yoke_harness.ssh_linux_golden_diagnostics import run_golden_command
from yoke_harness.ssh_windows_host_operations import SshWindowsHostOperations
from yoke_contracts.test_machine_types import HostActionResult
from yoke_contracts.windows_wsl_command import windows_wsl_command, windows_wsl_input


SETTINGS = {
    "resource_name": "windows-lab",
    "host": "windows.invalid",
    "user": "Administrator",
    "os": "wsl",
    "operating_notes": "WSL2",
    "golden_baseline_path": "/var/lib/yoke-golden/tester/home",
}


@pytest.mark.parametrize("exit_code", [124, 255])
def test_windows_transport_failure_does_not_blame_the_wsl_user(monkeypatch, exit_code):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda argv, **kw: subprocess.CompletedProcess(
            argv, exit_code, "", "SSH connection failed opaque-key"
        ),
    )
    with pytest.raises(HostControlLocalError) as raised:
        SshWindowsHostOperations(
            settings=SETTINGS, key_path="/private/key", secret_values=("opaque-key",)
        )
    assert raised.value.code == "ssh_unavailable"
    assert raised.value.exit_code == exit_code
    assert "opaque-key" not in str(raised.value)


def _decoded(command):
    return base64.b64decode(command.rsplit(" ", 1)[1]).decode("utf-16-le")


def _linux_command(command):
    payload = re.search(r"printf %s ([A-Za-z0-9+/=]+) \| base64 -d", _decoded(command))
    assert payload is not None
    return base64.b64decode(payload[1]).decode("utf-8")


def test_shell_metacharacters_survive_the_windows_shell():
    command = "printf '%s' \"$HOME & %PATH% café\"\nexit 7"
    wrapped = windows_wsl_command(command)
    script = _decoded(wrapped)
    assert _linux_command(wrapped) == command
    assert "wsl.exe --cd '~' -e /bin/bash -lc" in script
    assert script.endswith("; exit $LASTEXITCODE")
    assert "%PATH%" not in wrapped and "$HOME" not in wrapped


@pytest.mark.linux_only(reason='Executes the Linux Bash process-substitution semantics used by WSL2')
def test_long_commands_preserve_original_stdin_and_exit_status():
    stdin = '{"absent_paths": ["café", "two words"]}'
    program = "# long golden-like program\n" * 1000
    program += "import sys; print(sys.stdin.read()); sys.exit(7)"
    command = shlex.join(["/usr/bin/python3", "-c", program])
    reader, framed_input = windows_wsl_input(command, stdin)
    assert len(windows_wsl_command(reader)) < 8191
    result = subprocess.run(
        ["/bin/bash", "-lc", reader],
        input=framed_input,
        text=True,
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 7
    assert result.stdout == stdin + "\n"


@pytest.mark.parametrize("kernel", ["6.6.87.2-microsoft-standard-WSL2", "legacy"])
def test_windows_ssh_requires_wsl2_and_non_root_facts(monkeypatch, kernel):
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        assert "read -r payload" in _linux_command(argv[-1])
        script = base64.b64decode(kwargs["input"].split("\n", 1)[0]).decode()
        output = (
            kernel
            if "osrelease" in script
            else json.dumps(
                {
                    "home": "/home/tester",
                    "shell": "/bin/bash",
                    "uid": 1000,
                    "os": "Linux",
                }
            )
        )
        return subprocess.CompletedProcess(argv, 0, output, "")

    monkeypatch.setattr(subprocess, "run", run)
    if kernel == "legacy":
        with pytest.raises(Exception, match="default distro must run WSL2"):
            SshWindowsHostOperations(settings=SETTINGS, key_path="/private/key")
        return
    control = SshWindowsHostOperations(settings=SETTINGS, key_path="/private/key")
    assert control.home == "/home/tester"
    receipt = control.check_connection()
    assert receipt.ok and receipt.evidence["os"] == "wsl"
    result = control.run_command(["printf", "%s", "two words"])
    assert result.returncode == 0
    assert (
        "two words"
        in base64.b64decode(calls[-1][1]["input"].split("\n", 1)[0]).decode()
    )
    assert all("wsl.exe --cd '~' -e" in _decoded(argv[-1]) for argv, _ in calls)


def test_windows_baselines_use_the_linux_restore_boundary():
    assert validate_test_machine_settings(SETTINGS)["os"] == "wsl"
    selected = []
    control = SimpleNamespace(
        os="wsl",
        reach_baseline=lambda name: (
            selected.append(name) or HostActionResult(True, {"home": "/home/tester"})
        ),
    )
    assert run_host_baseline(control, "fresh-host").ok
    assert selected == ["fresh-host"]


def test_machine_qa_factory_selects_windows_transport(monkeypatch):
    monkeypatch.setattr(SshWindowsHostControl, "__init__", lambda *a: None)
    control = host_control_for(SimpleNamespace(settings=SETTINGS))
    assert isinstance(control, SshWindowsHostControl)


def test_native_windows_never_falls_back_to_the_wsl_or_linux_transport(monkeypatch):
    from yoke_core.domain.ssh_native_windows_host_control import SshNativeWindowsHostControl

    monkeypatch.setattr(SshNativeWindowsHostControl, '__init__', lambda *args: None)
    native = {**SETTINGS, 'os':'windows', 'golden_baseline_path':r'C:\YokeQa\goldens\baseline'}
    control = host_control_for(SimpleNamespace(settings=native))
    assert isinstance(control,SshNativeWindowsHostControl)
    assert not isinstance(control,SshWindowsHostControl)


def test_windows_golden_command_forwards_private_ssh_log(tmp_path, monkeypatch):
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs.get("input")))
        return subprocess.CompletedProcess(argv, 255, "archive-ok", "archive-err")

    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    control = object.__new__(SshWindowsHostOperations)
    control._key_path = Path("/private/key")
    control._host = "windows.invalid"
    control._user = "Administrator"
    control._control_path = tmp_path / "absent-socket"
    control.secret_values = ()
    command = "printf '%s' \"$HOME\""
    stdin = '{"probe": true}'
    result, evidence = run_golden_command(
        control, command, input_text=stdin, timeout=30
    )
    reader, framed_input = windows_wsl_input(command, stdin)
    assert result.returncode == 255
    assert result.stdout == "archive-ok" and result.stderr == "archive-err"
    assert len(calls) == 2
    debug_argv, debug_input = calls[0]
    assert debug_argv[1:4] == ["-vvv", "-E", evidence["ssh_client_log"]]
    assert _linux_command(debug_argv[-1]) == reader
    assert debug_input == framed_input
    assert base64.b64decode(framed_input.split("\n", 1)[0]) == command.encode()
    assert framed_input.endswith(stdin)
    journal_argv, journal_input = calls[1]
    assert "-E" not in journal_argv
    journal_command = base64.b64decode(journal_input.split("\n", 1)[0]).decode()
    assert journal_command.startswith("sudo -n journalctl ")
    journal_reader, journal_framed = windows_wsl_input(journal_command, None)
    assert _linux_command(journal_argv[-1]) == journal_reader
    assert journal_input == journal_framed


def test_ad_hoc_exec_windows_command_enters_wsl(monkeypatch, tmp_path):
    from yoke_cli.commands import test_machine_desktop_lease as custody
    from yoke_cli.commands.adapters import test_machine_exec as adapter
    from yoke_contracts.api.function_call import FunctionCallResponse
    from yoke_core.domain import cloud_machine_power

    calls = []
    lease = FunctionCallResponse(
        success=True, function="lease", version="v1", result={"claim_id": 7}
    )
    monkeypatch.setattr(custody.dispatcher, "call_dispatcher", lambda **kw: lease)
    monkeypatch.setattr(cloud_machine_power, "power_on", lambda *a: None)
    monkeypatch.setattr(adapter, "ensure_handlers_loaded", lambda: None)
    monkeypatch.setattr(
        adapter, "build_actor", lambda **kw: SimpleNamespace(session_id="mine")
    )
    monkeypatch.setattr(adapter.machine_config, "yoke_home", lambda: tmp_path)
    monkeypatch.setattr(
        adapter,
        "call_dispatcher",
        lambda **kw: FunctionCallResponse(
            success=True,
            function="test_machine.get",
            version="v1",
            result={"settings": SETTINGS, "test_machine": "windows-lab"},
        ),
    )
    monkeypatch.setattr(
        "yoke_harness.test_machine_remote_exec.run_remote_command",
        lambda **kw: calls.append(kw) or subprocess.CompletedProcess([], 7, "", ""),
    )
    assert adapter.test_machine_exec(["--", "exit 7"]) == 7
    assert _linux_command(calls[0]["command"][0]) == "exit 7"


def test_gui_command_uses_native_windows_desktop_task(monkeypatch, tmp_path):
    from yoke_harness import machine_gui_command as gui
    from yoke_harness.native_windows import desktop

    from yoke_contracts.machine_config import capability_secret_store
    from yoke_harness.native_windows import transport

    calls=[]
    key = tmp_path / 'ssh_private_key'
    key.write_text('key')
    facts = {'os':'Windows','admin':False,'home':r'C:\Users\qa','shell':'powershell.exe',
             'edition':'Windows 11 Pro','build':'26100','user':r'host\qa'}
    monkeypatch.setenv('SSH_AUTH_SOCK','test-agent')
    monkeypatch.setattr(capability_secret_store,'test_machine_secret_path',lambda name,k:key)
    monkeypatch.setattr(transport.WindowsTransport,'_host_facts',lambda self:setattr(self,'windows_facts',facts) or facts)
    monkeypatch.setattr(desktop,'desktop_script',lambda control,script,**kwargs:calls.append(script) or subprocess.CompletedProcess([],0,'native',''))
    result = gui.run_gui_command(settings={**SETTINGS,'os':'windows'},argv=['yoke.cmd'],yoke_home=tmp_path)
    assert result.stdout == 'native'
    assert 'yoke.cmd' in calls[0]
    assert 'wsl.exe' not in calls[0]



@pytest.mark.parametrize("target", ["windows", "xfce"])
def test_wsl_mission_routes_commands_and_screenshots_to_selected_desktop(monkeypatch, target):
    from yoke_harness import ssh_windows_host_operations as windows

    calls = []
    console = object()
    control = object.__new__(SshWindowsHostOperations)
    control.windows_host = console
    control.wsl_desktop_session = validate_test_machine_settings(
        {**SETTINGS, "wsl_desktop_session": target}
    )["wsl_desktop_session"]

    def run_native(host, script, *, timeout):
        assert host is console
        assert "wsl.exe --cd" in script
        calls.append(("windows", timeout))
        return subprocess.CompletedProcess([], 0, "", "")

    def run_linux(host, argv, *, required_session_context, timeout):
        assert host is control
        assert argv == ["yoke", "ui", "up"]
        assert required_session_context == "gui"
        calls.append(("xfce", timeout))
        return subprocess.CompletedProcess([], 0, "", "")

    monkeypatch.setattr(windows, "desktop_script", run_native)
    monkeypatch.setattr(windows.SshLinuxHostOperations, "run_command", run_linux)
    def captured(source):
        return lambda host, **_: HostActionResult(True, {"source": source, "host": host})

    monkeypatch.setattr(windows, "capture_desktop", captured("windows"))
    monkeypatch.setattr(windows.SshLinuxHostOperations, "capture_screenshot", captured("xfce"))

    result = control.run_command(["yoke", "ui", "up"], required_session_context="gui", timeout=90)
    assert result.returncode == 0 and calls == [(target, 90)]
    shot = control.capture_screenshot().evidence
    assert shot["source"] == target
    assert shot["host"] is (console if target == "windows" else control)


@pytest.mark.parametrize("wsl", [False, True])
@pytest.mark.parametrize("ready", [False, True])
def test_interactive_windows_console_probe_requires_receipt(monkeypatch, wsl, ready):
    from yoke_harness.native_windows import console

    control = object()

    def task(host, script, *, timeout):
        assert host is control and timeout == 30
        assert "Get-Process explorer" in script
        assert "InputDesktopReady()" in script
        assert ("wsl.exe" in script) is wsl
        resolution = "" if wsl else "1920x1080\n"
        return subprocess.CompletedProcess([], 0, resolution + console.RECEIPT if ready else "", "")

    monkeypatch.setattr(console.desktop, "desktop_script", task)
    result = console.probe_console(control, wsl=wsl)
    assert result.ok is ready
    if ready:
        assert result.evidence == {
            "desktop_session": "windows_console", "wsl_started": wsl,
            **({} if wsl else {"resolution": "1920x1080"}),
        }
    else:
        assert result.error_code == "windows_console_not_ready"
        assert "the next lease cold-boots and autologon signs in" in result.evidence["recovery"]


def wsl_console_screenshot(monkeypatch):
    """Capture through a WSL machine whose desktop is the Windows console."""
    from runtime.api.domain.machine_screenshot_test_support import screenshot_result
    from yoke_harness import ssh_windows_host_operations as windows

    native = screenshot_result()
    native.evidence.update(os="windows", desktop_session="interactive")
    monkeypatch.setattr(windows, "capture_desktop", lambda host, **_: native)
    control = object.__new__(SshWindowsHostOperations)
    control.windows_host = object()
    control.wsl_desktop_session = "windows"
    return control.capture_screenshot()


def test_wsl_windows_console_screenshot_names_the_wsl_machine(monkeypatch):
    result = wsl_console_screenshot(monkeypatch)
    assert result.ok and result.error_code is None
    assert result.evidence["os"] == "wsl"
    assert result.evidence["desktop_session"] == "windows_console"
    assert result.evidence["capture_artifact"]["token"] == "desktop"
