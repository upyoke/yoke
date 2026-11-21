"""The Python installer preserves successful installation across setup exits."""

import subprocess
from types import SimpleNamespace

import pytest

from public_installer_helpers import RecordingRunner, load_installer, write_channel
from tests.installer.public_installer_test_support import _status_ok


@pytest.mark.parametrize(
    "status, exit_code, token",
    [
        (0, 0, None),
        (130, 0, "setup_skipped"),
        ("interrupt", 0, "setup_skipped"),
        (1, 2, "setup_failed"),
        ("install failure", 1, "shell_path_setup_failed"),
    ],
)
def test_python_installer_exit_on_windows(
    monkeypatch, tmp_path, capsys, status, exit_code, token
):
    module = load_installer()
    release = write_channel(tmp_path, version="1.2.3")
    yoke_bin = str(tmp_path / "yoke.cmd")
    setup_args = [yoke_bin, "setup", "--post-install"]
    path_rc = int(status == "install failure")
    responses = {
        (yoke_bin, "status", "--json"): _status_ok("1.2.3"),
        (yoke_bin, "path", "fix", "--yes", "--json"): subprocess.CompletedProcess(
            [], path_rc, "", "fixture PATH failure" if path_rc else ""
        ),
    }
    runner = RecordingRunner(stdout="1.2.3", responses=responses)

    def run(command):
        if command == setup_args:
            runner.commands.append(command)
            if status == "interrupt":
                raise KeyboardInterrupt
            return subprocess.CompletedProcess(command, status)
        return runner(command)

    monkeypatch.setattr(module, "require_native_windows_python", lambda: None)
    monkeypatch.setattr(
        module.Installer, "_resolve_installed_yoke_bin", lambda _: yoke_bin
    )
    monkeypatch.setattr(module, "run_command_capture", run)
    monkeypatch.setattr(module, "subprocess", SimpleNamespace(run=run))
    monkeypatch.setattr(
        module,
        "sys",
        SimpleNamespace(
            platform="win32",
            stdin=SimpleNamespace(isatty=lambda: True),
            stdout=module.sys.stdout,
            stderr=module.sys.stderr,
        ),
    )
    monkeypatch.delenv("YOKE_NO_SETUP", raising=False)
    monkeypatch.delenv("YOKE_INSTALL_YES", raising=False)

    assert module.main(["--base-url", release["base_url"]]) == exit_code
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert (setup_args in runner.commands) == (path_rc == 0)
    assert "setup_incomplete" not in output
    assert ("setup_failed:" in output.split()) == (exit_code == 2)
    assert ("setup_skipped:" in output.split()) == (token == "setup_skipped")
    if token is not None:
        assert token in output
    if token in {"setup_skipped", "setup_failed"}:
        assert f"{token}: Yoke v1.2.3 is installed" in output
        assert "resume with yoke setup in a new terminal" in output


def test_python_installer_reserves_exit_two_for_post_install_setup(capsys):
    assert load_installer().main(["--invalid-option"]) == 1
    assert "unrecognized arguments" in capsys.readouterr().err
