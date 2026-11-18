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

    def __init__(self, *, equivalent=True):
        self.ssh_scripts = []
        self.ssh_commands = []
        self.equivalent = equivalent
        self.calls = []

    def reset_installer_test_host(self):
        self.calls.append("reset")
        return HostActionResult(True, {"operation": "reset"})

    def prove_user_equivalent(self):
        self.calls.append("prove")
        if self.equivalent:
            return HostActionResult(True, {"probes": "passed"})
        return HostActionResult(False, {"probes": "claude signed out"}, "baseline_probe_failed")

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


def test_fresh_host_proves_user_equivalence_and_never_installs(console):
    control = _Control()
    result = baseline.reach_baseline(control, "fresh-host")
    assert result.ok
    assert result.evidence["user_equivalence"] == {"probes": "passed"}
    assert control.calls == ["reset", "prove"]
    assert console == []


@pytest.mark.parametrize("name", ["fresh-host", "shell-preconfigured"])
def test_unproven_user_equivalence_fails_before_any_install(console, name):
    control = _Control(equivalent=False)
    result = baseline.reach_baseline(control, name)
    assert not result.ok
    assert result.error_code == "baseline_probe_failed"
    assert console == [] and control.ssh_commands == []


def test_qa_baselines_reach_the_native_windows_operation():
    from yoke_core.domain.host_baseline_operations import run_host_baseline

    reached = []
    control = SimpleNamespace(
        os="windows",
        reach_baseline=lambda name: reached.append(name) or HostActionResult(True, {}),
    )
    assert run_host_baseline(control, "shell-preconfigured").ok
    assert reached == ["shell-preconfigured"]


def test_qa_baselines_refuse_an_unknown_host_os():
    from yoke_core.domain.host_baseline_operations import run_host_baseline

    with pytest.raises(ValueError, match="host_baseline_os_unsupported"):
        run_host_baseline(SimpleNamespace(os="plan9"), "fresh-host")


def test_console_install_failure_keeps_the_tail_of_both_streams(monkeypatch, console):
    uv_lines = [f"uv line {n}" for n in range(60)]

    def failing(control, script, *, timeout=60, hidden=False):
        return subprocess.CompletedProcess(
            [], 1, "\n".join(uv_lines),
            "python_bootstrap_failed: uv exited 2 while preparing Python 3.12.16",
        )

    monkeypatch.setattr(baseline, "desktop_script", failing)
    result = baseline.reach_baseline(_Control(), "shell-preconfigured")
    recovery = result.evidence["recovery"]
    assert result.error_code == "windows_baseline_install_failed"
    assert "python_bootstrap_failed: uv exited 2" in recovery
    assert "uv line 59" in recovery and "uv line 20" in recovery
    assert "uv line 19\n" not in recovery
    assert recovery.index("install stderr") < recovery.index("install stdout")


def test_silent_console_install_failure_still_names_a_recovery(monkeypatch, console):
    monkeypatch.setattr(
        baseline, "desktop_script",
        lambda control, script, **kw: subprocess.CompletedProcess([], 3, "", ""),
    )
    result = baseline.reach_baseline(_Control(), "shell-preconfigured")
    assert "exited 3 without output" in result.evidence["recovery"]
