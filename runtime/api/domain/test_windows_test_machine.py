"""Windows transport reaches Linux operations without interpreting Linux argv."""

from __future__ import annotations

import base64
import json
import re
import shlex
import subprocess
import sys
from types import SimpleNamespace

import pytest

from yoke_contracts.machine_config.test_machine import validate_test_machine_settings
from yoke_contracts.machine_qa_failures import HostControlLocalError
from yoke_core.domain.host_baseline_operations import run_host_baseline
from yoke_core.domain.machine_qa_host_control import host_control_for
from yoke_core.domain.ssh_windows_host_control import SshWindowsHostControl
from yoke_harness.ssh_windows_host_operations import SshWindowsHostOperations
from yoke_harness.test_machine_types import HostActionResult
from yoke_harness.windows_wsl_command import windows_wsl_command, windows_wsl_input


SETTINGS = {
    "resource_name": "windows-lab",
    "host": "windows.invalid",
    "user": "Administrator",
    "os": "windows",
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


@pytest.mark.skipif(
    sys.platform != "linux",
    reason="Executes the Linux Bash process-substitution semantics used by WSL2",
)
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
    assert receipt.ok and receipt.evidence["os"] == "windows"
    assert receipt.evidence["execution_context"] == "wsl2"
    result = control.run_command(["printf", "%s", "two words"])
    assert result.returncode == 0
    assert (
        "two words"
        in base64.b64decode(calls[-1][1]["input"].split("\n", 1)[0]).decode()
    )
    assert all("wsl.exe --cd '~' -e" in _decoded(argv[-1]) for argv, _ in calls)


def test_windows_baselines_use_the_linux_restore_boundary():
    assert validate_test_machine_settings(SETTINGS)["os"] == "windows"
    selected = []
    control = SimpleNamespace(
        os="windows",
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


def test_ad_hoc_exec_windows_command_enters_wsl(monkeypatch, tmp_path):
    from yoke_cli.commands.adapters import test_machine_exec as adapter
    from yoke_contracts.api.function_call import FunctionCallResponse

    calls = []
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
            result={"settings": SETTINGS, "machine": "windows-lab"},
        ),
    )
    monkeypatch.setattr(
        "yoke_harness.test_machine_remote_exec.run_remote_command",
        lambda **kw: calls.append(kw) or subprocess.CompletedProcess([], 7, "", ""),
    )
    assert adapter.test_machine_exec(["--project", "yoke", "--", "exit 7"]) == 7
    assert _linux_command(calls[0]["command"][0]) == "exit 7"
