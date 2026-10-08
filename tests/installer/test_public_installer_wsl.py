"""Installation keeps the OS prompt reachable and verifies WSL boot changes."""

import io
import subprocess

import pytest

from public_installer_helpers import (
    PUBLISHED_RELEASE_RECORD,
    RecordingRunner,
    load_installer,
)


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
        fetcher=lambda _url: PUBLISHED_RELEASE_RECORD,
        stdout=io.StringIO(),
    )
    installer.run()
    assert runner.commands == []


@pytest.mark.parametrize("unavailable", ["old_version", "interop"])
def test_lifetime_warning_allows_installer_to_finish(monkeypatch, unavailable):
    from yoke_harness import wsl_systemd, wsl_lifetime

    module = load_installer()
    output = io.StringIO()
    installer = module.Installer(
        module.parse_args(["--version", "1.2.3", "--no-setup"]),
        runner=RecordingRunner(),
        stdout=output,
    )
    monkeypatch.setattr(installer, "_run_uv_install", lambda command: False)
    monkeypatch.setattr(installer, "_resolve_installed_yoke_bin", lambda: "/bin/yoke")
    monkeypatch.setattr(installer, "_smoke_yoke", lambda binary: "1.2.3")
    monkeypatch.setattr(installer, "_product_boundary_audit", lambda **kw: None)
    monkeypatch.setattr(installer, "_repair_credential_helper", lambda binary: None)
    monkeypatch.setattr(installer, "_record_distribution", lambda binary: None)
    monkeypatch.setattr(installer, "_advise_path", lambda: None)
    monkeypatch.setattr(wsl_systemd, "is_wsl", lambda: True)
    monkeypatch.setattr(wsl_systemd, "_setup_systemd", lambda **kw: "already_running")
    monkeypatch.setattr(
        wsl_lifetime.shutil,
        "which",
        lambda name: name if unavailable == "old_version" else None,
    )
    monkeypatch.setattr(wsl_lifetime, "_run", lambda command: "WSL version: 2.5.3.0")
    monkeypatch.setattr(
        wsl_lifetime, "_config_path", lambda: pytest.fail("cannot configure lifetime")
    )
    warnings = []

    def setup(command):
        assert wsl_systemd.setup(emit=warnings.append) == "already_running"
        return subprocess.CompletedProcess(command, 0)

    installer.terminal_runner = setup
    installer.run()
    assert "is ready" in output.getvalue()
    assert "Warning:" in warnings[0] and "wsl --update" in warnings[0]
