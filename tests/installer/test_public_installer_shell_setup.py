"""Installer delegates shell setup without inheriting its temporary PATH."""

import io
import subprocess
import pytest
from public_installer_helpers import RecordingRunner, load_installer


def _installer(monkeypatch, runner, *, resolve_bin=True):
    module = load_installer()
    options = module.InstallOptions(
        channel="stable",
        version="1.2.3",
        yes=True,
        dry_run=False,
        base_url="https://api.upyoke.com",
        no_setup=True,
    )
    installer = module.Installer(options, runner=runner, stdout=io.StringIO())
    if resolve_bin:
        monkeypatch.setattr(
            installer, "_resolve_installed_yoke_bin", lambda: "/tmp/bin/yoke"
        )
    monkeypatch.setattr(installer, "_smoke_yoke", lambda _: "1.2.3")
    monkeypatch.setattr(installer, "_product_boundary_audit", lambda **_: None)
    monkeypatch.setattr(installer, "_repair_credential_helper", lambda _: None)
    return module, installer


def test_installer_runs_owned_shell_setup_after_install(monkeypatch):
    runner = RecordingRunner()
    _, installer = _installer(monkeypatch, runner)
    installer.run()
    assert runner.commands[0][:3] == ["uv", "tool", "install"]
    assert runner.commands[1] == ["/tmp/bin/yoke", "path", "fix", "--yes", "--json"]
    assert "Add Yoke to PATH:" not in installer.stdout.getvalue()


def test_installer_names_shell_failure_before_ready(monkeypatch):
    runner = RecordingRunner(
        responses={
            (
                "/tmp/bin/yoke",
                "path",
                "fix",
                "--yes",
                "--json",
            ): subprocess.CompletedProcess(
                [], 1, "shell_path_unresolved: zsh non-login", ""
            )
        }
    )
    module, installer = _installer(monkeypatch, runner)
    with pytest.raises(module.InstallError, match="shell_path_setup_failed.*path fix"):
        installer.run()
    assert "is ready" not in installer.stdout.getvalue()


def test_rerun_from_unreloaded_shell_succeeds_with_new_terminal_hint(monkeypatch):
    monkeypatch.setenv("YOKE_INSTALL_INHERITED_PATH", "/usr/bin:/bin")
    _, installer = _installer(monkeypatch, RecordingRunner())
    installer.run()
    assert "Open a new terminal to use Yoke." in installer.stdout.getvalue()


@pytest.mark.parametrize(
    ("inherited", "hint"),
    [("/usr/bin:/bin", True), ("/tmp/bin:/usr/bin:/bin", False)],
)
def test_path_hint_follows_the_callers_path(monkeypatch, inherited, hint):
    # The shim puts the bin dir on the installer's own PATH, so yoke always
    # resolves there; only the caller's PATH decides whether the hint is needed.
    monkeypatch.setenv("PATH", "/tmp/bin:/usr/bin:/bin")
    monkeypatch.setenv("YOKE_INSTALL_INHERITED_PATH", inherited)
    _, installer = _installer(monkeypatch, RecordingRunner())
    installer.which = lambda _: "/tmp/bin/yoke"
    installer.run()
    assert ("Open a new terminal to use Yoke." in installer.stdout.getvalue()) is hint
