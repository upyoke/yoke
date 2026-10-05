"""Installation keeps the OS prompt reachable and verifies WSL boot changes."""

import io
import subprocess

import pytest

from public_installer_helpers import RecordingRunner, load_installer


def test_installer_runs_wsl_setup_before_ready(monkeypatch):
    module = load_installer()
    runner = RecordingRunner()
    output = io.StringIO()
    installer = module.Installer(
        module.parse_args(["--version", "1.2.3", "--no-setup"]),
        runner=runner,
        stdout=output,
    )
    monkeypatch.setattr(installer, "_run_uv_install", lambda command: False)
    monkeypatch.setattr(installer, "_resolve_installed_yoke_bin", lambda: "/bin/yoke")
    monkeypatch.setattr(installer, "_smoke_yoke", lambda binary: "1.2.3")
    monkeypatch.setattr(installer, "_product_boundary_audit", lambda **kw: None)
    monkeypatch.setattr(installer, "_repair_credential_helper", lambda binary: None)
    monkeypatch.setattr(installer, "_record_distribution", lambda binary: None)
    monkeypatch.setattr(installer, "_advise_path", lambda: None)
    installer.run()
    assert ["/bin/yoke", "wsl", "setup"] in runner.commands
    assert "is ready" in output.getvalue()


def test_failed_wsl_setup_does_not_print_ready(monkeypatch):
    module = load_installer()
    output = io.StringIO()
    runner = RecordingRunner()
    installer = module.Installer(
        module.parse_args(["--version", "1.2.3"]),
        runner=runner,
        stdout=output,
    )
    monkeypatch.setattr(installer, "_run_uv_install", lambda command: False)
    monkeypatch.setattr(installer, "_resolve_installed_yoke_bin", lambda: "/bin/yoke")
    monkeypatch.setattr(installer, "_smoke_yoke", lambda binary: "1.2.3")
    monkeypatch.setattr(installer, "_product_boundary_audit", lambda **kw: None)
    monkeypatch.setattr(installer, "_repair_credential_helper", lambda binary: None)
    monkeypatch.setattr(installer, "_record_distribution", lambda binary: None)
    installer.terminal_runner = lambda command: subprocess.CompletedProcess(command, 1)
    with pytest.raises(module.InstallError, match="wsl_systemd_setup_failed"):
        installer.run()
    assert "is ready" not in output.getvalue()


def test_installer_setup_subprocess_inherits_the_terminal():
    module = load_installer()
    installer = module.Installer(module.parse_args([]))
    assert installer.terminal_runner is subprocess.run


def test_dry_run_does_not_execute_wsl_setup():
    module = load_installer()
    runner = RecordingRunner()
    installer = module.Installer(
        module.parse_args(["--version", "1.2.3", "--dry-run"]),
        runner=runner,
        stdout=io.StringIO(),
    )
    installer.run()
    assert runner.commands == []
