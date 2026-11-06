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
            (yoke_bin, "hook", "resident", "restart"): subprocess.CompletedProcess(
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
