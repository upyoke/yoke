"""The public installer owns dashboard restart and enforces its receipt."""

import io
import json
import subprocess

import pytest

from public_installer_helpers import RecordingRunner, load_installer, write_channel
from public_installer_test_support import _installed_yoke_path, _options, _status_ok


@pytest.mark.parametrize("already", [False, True])
@pytest.mark.parametrize("restarted", [False, True])
def test_install_and_reinstall_restart_before_ready(
    tmp_path, monkeypatch, already, restarted
):
    module = load_installer()
    release = write_channel(tmp_path, version="2.0.0")
    binary = _installed_yoke_path(tmp_path, monkeypatch)
    output = io.StringIO()
    command = [binary, "ui", "restart-running", "--json"]
    runner = RecordingRunner(
        stdout="2.0.0\n",
        responses={
            (binary, "status", "--json"): _status_ok("2.0.0"),
            tuple(command): subprocess.CompletedProcess(
                command, 0, json.dumps({"ok": True, "restarted": restarted}), ""
            ),
        },
    )
    installer = module.Installer(
        _options(module, base_url=release["base_url"], no_setup=True),
        runner=runner,
        stdout=output,
        which=lambda name: "/usr/bin/" + name,
    )
    monkeypatch.setattr(installer, "_run_uv_install", lambda argv: already)
    installer.run()
    assert command in runner.commands
    assert runner.commands.index(command) > runner.commands.index([binary, "--version"])
    text = output.getvalue()
    if restarted:
        assert text.index("Restarted the running dashboard") < text.index(
            "already installed" if already else "is ready"
        )
    else:
        assert "Restarted the running dashboard" not in text


@pytest.mark.parametrize(
    "rc,payload,reason",
    [
        (1, "", "ui_restart_failed"),
        (0, "not json", "ui_restart_result_invalid"),
        (0, '{"ok":false,"restarted":true}', "ui_restart_result_invalid"),
        (0, '{"ok":true,"restarted":"yes"}', "ui_restart_result_invalid"),
    ],
)
def test_restart_failure_never_reports_ready(
    tmp_path, monkeypatch, rc, payload, reason
):
    module = load_installer()
    release = write_channel(tmp_path, version="2.0.0")
    binary = _installed_yoke_path(tmp_path, monkeypatch)
    output = io.StringIO()
    command = [binary, "ui", "restart-running", "--json"]
    runner = RecordingRunner(
        stdout="2.0.0\n",
        responses={
            (binary, "status", "--json"): _status_ok("2.0.0"),
            tuple(command): subprocess.CompletedProcess(
                command, rc, payload, "restart failed"
            ),
        },
    )
    installer = module.Installer(
        _options(module, base_url=release["base_url"]),
        runner=runner,
        stdout=output,
        which=lambda name: "/usr/bin/" + name,
    )
    with pytest.raises(module.InstallError, match=reason):
        installer.run()
    assert "is ready" not in output.getvalue()
    assert "already installed" not in output.getvalue()
