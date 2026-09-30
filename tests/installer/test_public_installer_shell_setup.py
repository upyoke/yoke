"""Installer delegates shell setup without inheriting its temporary PATH."""

import io
import subprocess
import pytest
from public_installer_helpers import RecordingRunner, load_installer


def _installer(monkeypatch, runner):
    module = load_installer()
    options = module.InstallOptions(
        channel="stable",
        version="1.2.3",
        yes=True,
        dry_run=False,
        base_url="https://api.upyoke.com",
        no_onboard=True,
    )
    installer = module.Installer(options, runner=runner, stdout=io.StringIO())
    monkeypatch.setattr(
        installer, "_resolve_installed_yoke_bin", lambda: "/tmp/bin/yoke"
    )
    monkeypatch.setattr(installer, "_smoke_yoke", lambda _: "1.2.3")
    monkeypatch.setattr(installer, "_product_boundary_audit", lambda **_: None)
    monkeypatch.setattr(installer, "_repair_credential_helper", lambda _: None)
    return module, installer


def test_installer_runs_uv_shell_setup_after_install(monkeypatch):
    runner = RecordingRunner()
    _, installer = _installer(monkeypatch, runner)
    installer.run()
    assert runner.commands[0][:3] == ["uv", "tool", "install"]
    assert runner.commands[1] == ["uv", "tool", "update-shell"]


def test_installer_names_uv_shell_failure(monkeypatch):
    runner = RecordingRunner(
        responses={
            ("uv", "tool", "update-shell"): subprocess.CompletedProcess(
                [], 1, "", "permission denied"
            )
        }
    )
    module, installer = _installer(monkeypatch, runner)
    with pytest.raises(
        module.InstallError, match="uv_shell_update_failed.*uv tool update-shell"
    ):
        installer.run()


def test_shell_update_uses_inherited_path_and_absolute_uv(monkeypatch):
    module = load_installer()
    monkeypatch.setenv("PATH", "/temporary/bin:/usr/bin:/bin")
    monkeypatch.setenv("YOKE_INSTALL_INHERITED_PATH", "/usr/bin:/bin")
    monkeypatch.setattr(module.shutil, "which", lambda _: "/temporary/bin/uv")
    captured = {}

    def run(command, **kwargs):
        captured.update(command=command, env=kwargs["env"])
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(module.subprocess, "run", run)
    module.run_command_capture(["uv", "tool", "update-shell"])
    assert captured["command"] == ["/temporary/bin/uv", "tool", "update-shell"]
    assert captured["env"]["PATH"] == "/usr/bin:/bin"
