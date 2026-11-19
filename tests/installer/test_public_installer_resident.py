"""Public installer readiness requires a warm, healthy hook evaluator."""

import io
import subprocess

import pytest

from public_installer_helpers import RecordingRunner, load_installer
from tests.installer.public_installer_test_support import _installed_yoke_path, _options, _status_ok


def test_evaluator_failure_never_reports_install_ready(tmp_path, monkeypatch):
    installer_mod = load_installer()
    yoke_bin = _installed_yoke_path(tmp_path, monkeypatch)
    output = io.StringIO()
    runner = RecordingRunner(
        stdout="2.0.0\n",
        responses={
            (yoke_bin, "status", "--json"): _status_ok("2.0.0"),
            (yoke_bin, "hook", "resident", "verify"): subprocess.CompletedProcess(
                [], 1, "YOKE_HOOK_RESIDENT_START_TIMEOUT: inspect evaluator.log", ""
            ),
        },
    )
    installer = installer_mod.Installer(
        _options(installer_mod, version="2.0.0"),
        runner=runner,
        which=lambda name: f"/usr/bin/{name}",
        stdout=output,
    )
    with pytest.raises(
        installer_mod.InstallError, match="YOKE_HOOK_RESIDENT_START_TIMEOUT"
    ):
        installer.run()
    assert "is ready" not in output.getvalue()


def test_update_to_a_release_without_verify_uses_its_restart_proof(
    tmp_path, monkeypatch
):
    """An update to an older release must not ask it for a command it lacks."""
    installer_mod = load_installer()
    yoke_bin = _installed_yoke_path(tmp_path, monkeypatch)
    output = io.StringIO()
    runner = RecordingRunner(
        stdout="1.9.0\n",
        responses={
            (yoke_bin, "status", "--json"): _status_ok("1.9.0"),
            (yoke_bin, "hook", "resident", "verify"): subprocess.CompletedProcess(
                [],
                2,
                "",
                "usage: yoke hook resident [-h] {restart,stop}\n"
                "yoke hook resident: error: argument action: invalid choice: "
                "'verify' (choose from 'restart', 'stop')\n",
            ),
            (yoke_bin, "hook", "resident", "restart"): subprocess.CompletedProcess(
                [], 0, "Hook evaluator: ready\n", ""
            ),
        },
    )
    installer = installer_mod.Installer(
        _options(installer_mod, version="1.9.0"),
        runner=runner,
        which=lambda name: f"/usr/bin/{name}",
        stdout=output,
    )
    installer.run()
    commands = [list(command) for command in runner.commands]
    verify = commands.index([yoke_bin, "hook", "resident", "verify"])
    assert commands.index([yoke_bin, "hook", "resident", "restart"]) == verify + 1
    assert "is ready" in output.getvalue()


def test_older_release_restart_failure_names_its_own_recovery(tmp_path, monkeypatch):
    installer_mod = load_installer()
    yoke_bin = _installed_yoke_path(tmp_path, monkeypatch)
    runner = RecordingRunner(
        stdout="1.9.0\n",
        responses={
            (yoke_bin, "status", "--json"): _status_ok("1.9.0"),
            (yoke_bin, "hook", "resident", "verify"): subprocess.CompletedProcess(
                [], 2, "", "error: argument action: invalid choice: 'verify'\n"
            ),
            (yoke_bin, "hook", "resident", "restart"): subprocess.CompletedProcess(
                [], 1, "YOKE_HOOK_RESIDENT_START_TIMEOUT: inspect evaluator.log", ""
            ),
        },
    )
    installer = installer_mod.Installer(
        _options(installer_mod, version="1.9.0"),
        runner=runner,
        which=lambda name: f"/usr/bin/{name}",
        stdout=io.StringIO(),
    )
    with pytest.raises(installer_mod.InstallError) as failure:
        installer.run()
    assert "hook_evaluator_readiness_failed" in str(failure.value)
    assert "YOKE_HOOK_RESIDENT_START_TIMEOUT" in str(failure.value)
    assert "run yoke hook resident restart" in str(failure.value)
