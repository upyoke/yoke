"""Project commands use one explicit shell and name missing installations."""

import subprocess

import pytest

from yoke_contracts import project_command_shell as shells


def test_posix_shell_is_fixed(monkeypatch):
    monkeypatch.setattr(shells.sys, "platform", "linux")
    assert shells.project_command_shell() == "/bin/sh"


def test_remote_posix_shell_does_not_use_the_windows_controller(monkeypatch):
    from yoke_contracts.qa_mission_scratch import stale_owner_marker_remove_argv

    monkeypatch.setattr(shells.sys, "platform", "win32")
    monkeypatch.setattr(shells.shutil, "which", lambda name: None)
    assert stale_owner_marker_remove_argv()[0] == "/bin/sh"


@pytest.mark.parametrize("layout", ["cmd", "bin", "mingw64/bin"])
def test_windows_shell_belongs_to_git_installation(tmp_path, monkeypatch, layout):
    root = tmp_path / "Git with spaces"
    git = root / layout / "git.exe"
    git.parent.mkdir(parents=True)
    git.touch()
    shell = root / "bin/sh.exe"
    shell.parent.mkdir(exist_ok=True)
    shell.touch()
    monkeypatch.setattr(shells.sys, "platform", "win32")
    monkeypatch.setattr(shells.shutil, "which", lambda name: str(git))
    assert shells.project_command_shell() == str(shell)


def test_windows_missing_sh_refuses_by_name(tmp_path, monkeypatch):
    monkeypatch.setattr(shells.sys, "platform", "win32")
    monkeypatch.setattr(shells.shutil, "which", lambda name: None)
    for key in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        monkeypatch.setenv(key, str(tmp_path / key))
    with pytest.raises(shells.ProjectCommandShellUnavailable) as caught:
        shells.project_command_shell()
    assert "project_command_shell_unavailable" in str(caught.value)
    assert "Install Git for Windows" in str(caught.value)


def test_windows_standard_install_without_git_on_path(tmp_path, monkeypatch):
    shell = tmp_path / "Git/bin/sh.exe"
    shell.parent.mkdir(parents=True)
    shell.touch()
    monkeypatch.setattr(shells.sys, "platform", "win32")
    monkeypatch.setattr(shells.shutil, "which", lambda name: None)
    monkeypatch.setenv("ProgramFiles", str(tmp_path))
    assert shells.project_command_shell() == str(shell)


def test_project_shell_executes_quoted_text_and_preserves_exit_status():
    result = subprocess.run(
        [shells.project_command_shell(), "-c", "printf '%s' 'two words'; exit 7"],
        capture_output=True, text=True, timeout=10,
    )
    assert result.stdout == "two words"
    assert result.returncode == 7
