"""Native host boundaries and recovery, exercised without a Windows controller."""

import base64
import json
import subprocess
from types import SimpleNamespace

import pytest

from yoke_contracts.machine_config.test_machine import validate_golden_baseline_path
from yoke_harness.native_windows.baseline import golden_path, profile_operation
from yoke_harness.native_windows.desktop import desktop_script
from yoke_harness.native_windows.transport import WindowsTransport, command
from yoke_harness.native_windows.journal import journal_operation
from yoke_core.domain.native_windows_fixture import NativeWindowsFixture


def completed(stdout="", returncode=0, stderr=""):
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


def test_powershell_arguments_remain_literal():
    assert command(["app.exe", "a'b; $(evil)", ""]) == "& 'app.exe' 'a''b; $(evil)' ''"
    control = object.__new__(WindowsTransport)
    control._key_path = "key"
    control._host = "host"
    control._user = "test"
    control._control_path = "socket"
    argv = control._ssh_argv('Write-Output "héllo"')
    script = base64.b64decode(argv[-1].split()[-1]).decode("utf-16-le")
    assert 'Write-Output "héllo"' in script
    assert "wsl" not in argv[-1]
    assert "catch" in script


@pytest.mark.parametrize(
    "path",
    [
        r"C:\Users\qa",
        r"C:\Users\qa\golden",
        r"C:\Users",
        r"C:\goldens\..\qa",
        "relative",
    ],
)
def test_golden_cannot_clear_or_live_inside_profile(path):
    with pytest.raises(ValueError, match="windows_golden_path_unsafe"):
        golden_path(SimpleNamespace(home=r"C:\Users\qa"), path)


def test_windows_golden_contract_is_controller_independent():
    path = r"C:\YokeQa\goldens\baseline"
    assert validate_golden_baseline_path(path) == path
    assert golden_path(SimpleNamespace(home=r"C:\Users\qa"), path) == path


def test_profile_copy_failure_does_not_report_restored():
    scripts = []

    def run(script, **kwargs):
        scripts.append(script)
        return completed(returncode=1, stderr="locked profile: close app and retry")

    result = profile_operation(
        SimpleNamespace(home=r"C:\Users\qa", _run=run),
        "reset",
        r"C:\YokeQa\goldens\baseline",
    )
    assert not result.ok
    assert result.error_code == "windows_profile_reset_failed"
    assert "robocopy.exe" in scripts[0]
    assert "SetEnvironmentVariable" in scripts[0]
    assert "Unregister-ScheduledTask" in scripts[0]
    assert "AppData\\Roaming\\Claude" in scripts[0]
    assert not any(line.startswith("+") for line in scripts[0].splitlines())


def test_desktop_task_uses_interactive_user_and_is_cleaned():
    scripts = []
    uploads = []
    control = SimpleNamespace(
        home=r"C:\Users\qa",
        upload_remote_text=lambda path, text: uploads.append((path, text)),
        read_remote_text=lambda path: json.dumps(
            {"exit_code": 7, "stdout": "native", "stderr": "expected"}
        ),
    )
    control._run = lambda script, **kwargs: scripts.append(script) or completed()
    result = desktop_script(control, "exit 7", timeout=1)
    assert result.returncode == 7
    assert result.stdout == "native"
    assert "-LogonType Interactive" in scripts[0]
    assert "-RunLevel Limited" in scripts[0]
    assert "Unregister-ScheduledTask" in scripts[-1]
    assert uploads[0][1] == "exit 7"


def test_journal_requires_a_lease_before_any_write():
    with pytest.raises(RuntimeError, match="windows_journal_lease_required"):
        journal_operation(SimpleNamespace(), "capture")


def test_interrupted_journal_recovers_before_capture_and_cleanup_retries():
    calls = []
    fail = [False]

    def journal(action):
        calls.append(action)
        if fail[0]:
            fail[0] = False
            raise RuntimeError("restore failed; repair original settings and retry")

    fixture = NativeWindowsFixture(SimpleNamespace(journal_settings=journal))
    assert calls == ["restore", "capture"]
    fail[0] = True
    assert not fixture.close().ok
    assert not fixture.closed
    assert fixture.close().ok
    assert calls == ["restore", "capture", "restore", "restore"]


def test_native_refresh_never_runs_posix_python(monkeypatch):
    from yoke_harness.golden_harness_clis import probe_harness_cli_versions

    seen = []

    def run(script, **kwargs):
        seen.append(script)
        return completed('{"codex":"1.2.3","claude-code":"2.3.4","cursor":"3.4.5"}')

    versions = probe_harness_cli_versions(SimpleNamespace(os="windows", _run=run))
    assert versions["codex"] == "1.2.3"
    assert "/usr/bin/python3" not in seen[0]
    assert "Get-Command" in seen[0]


def test_large_script_streams_utf8_bom_and_keeps_input(monkeypatch):
    from yoke_harness.ssh_test_machine_transport import SshTestMachineTransport

    calls = []

    def run(self, script, **kwargs):
        calls.append((script, kwargs))
        return completed()

    monkeypatch.setattr(SshTestMachineTransport, "_run", run)
    control = object.__new__(WindowsTransport)
    source = 'Write-Output "héllo"; ' * 1000
    control._run(source, input_text="private-input", timeout=17)
    assert base64.b64decode(calls[0][1]["input_text"]).decode("utf-8-sig") == source
    assert calls[1][1]["input_text"] == "private-input"
    assert "finally" in calls[1][0]
    assert "Remove-Item" in calls[1][0]


def test_native_console_task_outlives_open_and_is_owned_until_close(monkeypatch):
    from yoke_harness.native_windows.terminal import WindowsTerminal

    calls = []
    control = SimpleNamespace(
        home=r"C:\Users\qa",
        upload_remote_text=lambda *args: None,
        read_remote_text=lambda path: "456",
        _run=lambda script, **kwargs: calls.append(script) or completed(),
    )
    terminal = WindowsTerminal(control)
    assert terminal.launch("Write-Host native")
    assert terminal.pid == 456
    assert not any("Stop-ScheduledTask" in script for script in calls)
    assert terminal.close()
    assert any("Stop-ScheduledTask" in script for script in calls)
    assert any("Unregister-ScheduledTask" in script for script in calls)


def test_windows_probe_parser_accepts_native_executables_and_rejects_relative():
    from yoke_harness.ssh_mac_baseline_probes import parse_baseline_probes

    document = {
        "probes": [{"name": "native", "argv": [r"C:\Python\python.exe", "--version"]}]
    }
    assert (
        parse_baseline_probes(json.dumps(document))[0].argv[0]
        == r"C:\Python\python.exe"
    )
    document["probes"][0]["argv"][0] = r"Python\python.exe"
    with pytest.raises(ValueError, match="absolute program"):
        parse_baseline_probes(json.dumps(document))


def test_process_arguments_keep_empty_values_without_powershell_reparsing():
    from yoke_harness.native_windows.transport import process_script

    script = process_script(["app.exe", "", 'a"b', "x;y"])
    assert "$info.UseShellExecute=$false" in script
    assert subprocess.list2cmdline(["", 'a"b', "x;y"]).replace("'", "''") in script


def test_azure_script_error_with_exit_zero_is_a_refusal(monkeypatch):
    from yoke_harness.native_windows import provision

    replies = iter(
        [completed("ssh-ed25519 PUBLIC"), completed("ParserError: invalid script")]
    )
    monkeypatch.setattr(
        provision.subprocess, "run", lambda *args, **kwargs: next(replies)
    )
    monkeypatch.setattr(
        provision, "machine_capability_secret_path", lambda *args: "private-key"
    )
    with pytest.raises(RuntimeError, match="windows_openssh_bootstrap_failed"):
        provision.provision("project", "machine", "host", "group", "admin", "test")


def test_registered_native_goldens_are_checked_with_powershell():
    from yoke_harness.registered_golden_check import check_registered_goldens

    scripts = []
    path = r"C:\YokeQa\goldens\baseline"
    registered = [{"project": "project", "test_machine": "machine", "path": path}]
    check_registered_goldens(
        lambda script, **kwargs: scripts.append(script) or completed(),
        registered,
        os_name="windows",
    )
    assert "Get-Item -LiteralPath" in scripts[0]
    assert path in scripts[0]
    assert "for path in" not in scripts[0]


def test_native_retention_preserves_other_registered_goldens():
    from yoke_harness.native_windows.retention import retain

    scripts = []
    replies = iter(
        [
            completed(json.dumps(["qa-home-old", "qa-home-kept", "qa-home-new"])),
            completed(),
        ]
    )
    control = SimpleNamespace(
        home=r"C:\Users\qa",
        _user="qa",
        _run=lambda script, **kwargs: scripts.append(script) or next(replies),
    )
    removed = retain(
        control,
        r"C:\YokeQa\goldens\qa-home-new",
        [r"C:\YokeQa\goldens\qa-home-new", r"C:\YokeQa\goldens\qa-home-kept"],
    )
    assert removed == ("qa-home-old",)
    assert "qa-home-kept" not in scripts[1]
    assert "qa-home-new" not in scripts[1]
    assert "Remove-Item -LiteralPath" in scripts[1]


def test_bootstrap_waits_for_an_existing_guest_command(monkeypatch):
    from yoke_harness.native_windows import provision

    sleeps = []
    replies = iter(
        [
            completed("ssh-ed25519 PUBLIC"),
            completed(
                returncode=1, stderr="Run command extension execution is in progress"
            ),
            completed("ParserError: diagnosed guest failure"),
        ]
    )
    monkeypatch.setattr(
        provision.subprocess, "run", lambda *args, **kwargs: next(replies)
    )
    monkeypatch.setattr(
        provision, "machine_capability_secret_path", lambda *args: "private-key"
    )
    monkeypatch.setattr(provision.time, "sleep", lambda seconds: sleeps.append(seconds))
    with pytest.raises(RuntimeError, match="windows_openssh_bootstrap_failed"):
        provision.provision("project", "machine", "host", "group", "admin", "test")
    assert sleeps == [30]


def test_native_harness_requests_recognize_windows_launcher_paths():
    from yoke_harness.baseline_harness_requests import harness_request

    request = harness_request([r"C:\Users\qa\.local\bin\codex.cmd"])
    assert request.name == "Codex"
    assert request.argv[0].endswith("codex.cmd")
