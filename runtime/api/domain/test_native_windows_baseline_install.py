"""shell-preconfigured installs Yoke from the desktop console, as users do."""

import subprocess
from types import SimpleNamespace

import pytest

from yoke_contracts.test_machine_types import HostActionResult
from yoke_harness.native_windows import baseline


class _Control:
    home = r"C:\Users\yokeqa"
    path_state = SimpleNamespace(
        yoke_bin=r"C:\Users\yokeqa\.local\bin\yoke.cmd",
        tool_bin_dir=r"C:\Users\yokeqa\.local\bin",
    )

    def __init__(self):
        self.ssh_scripts = []
        self.ssh_commands = []

    def reset_installer_test_host(self):
        return HostActionResult(True, {"operation": "reset"})

    def _run(self, script, timeout=60):
        self.ssh_scripts.append(script)
        return subprocess.CompletedProcess([], 0, "", "")

    def run_command(self, argv, **kwargs):
        self.ssh_commands.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, "yoke 1.0", "")

    def probe_path(self, surface):
        return (self.path_state.tool_bin_dir,)


@pytest.fixture
def console(monkeypatch):
    from yoke_cli.config import distribution, machine_config

    monkeypatch.setattr(machine_config, "active_connection", lambda: "prod")
    monkeypatch.setattr(
        distribution, "origin_for_connection", lambda name: "https://api.example.test"
    )
    calls = []

    def desktop_script(control, script, *, timeout=60, hidden=False):
        calls.append({"script": script, "timeout": timeout, "hidden": hidden})
        return subprocess.CompletedProcess([], 0, "", "")

    monkeypatch.setattr(baseline, "desktop_script", desktop_script)
    return calls


def test_install_runs_through_console_bridge_and_ssh_only_verifies(console):
    control = _Control()
    result = baseline.reach_baseline(control, "shell-preconfigured")
    assert result.ok, result.evidence
    assert result.evidence["install_surface"] == "windows-console"
    [call] = console
    assert "'https://api.example.test/install.ps1'" in call["script"]
    assert "--yes --no-setup" in call["script"]
    assert call["timeout"] == 1200 and call["hidden"] is False
    assert not any("install.ps1" in script for script in control.ssh_scripts)
    assert control.ssh_commands == [([control.path_state.yoke_bin, "--version"], {})]


def test_console_install_failure_names_surface_and_recovery(monkeypatch, console):
    def failing(control, script, *, timeout=60, hidden=False):
        return subprocess.CompletedProcess(
            [], 1, "", "windows_untrusted_mount_point: run from a local PowerShell"
        )

    monkeypatch.setattr(baseline, "desktop_script", failing)
    control = _Control()
    result = baseline.reach_baseline(control, "shell-preconfigured")
    assert not result.ok
    assert result.error_code == "windows_baseline_install_failed"
    assert result.evidence["install_surface"] == "windows-console"
    assert "windows_untrusted_mount_point" in result.evidence["recovery"]
    assert control.ssh_commands == []


def test_fresh_host_never_installs(console):
    assert baseline.reach_baseline(_Control(), "fresh-host").ok
    assert console == []
