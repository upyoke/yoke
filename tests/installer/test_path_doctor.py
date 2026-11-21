"""Tests for the PATH doctor module and the `yoke path` CLI adapters."""

from __future__ import annotations

import errno
import json
import os
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

from yoke_cli.commands.adapters import path_doctor as cli
from yoke_cli.config import path_doctor as doctor
from yoke_cli.main import main as yoke_main
from yoke_cli.product_boundary_teaching import generate_teaching_audit

POSIX_SHELL = pytest.mark.posix_only(
    reason="local POSIX shell path state; Windows counterpart is tests/installer/test_windows_user_path.py"
)


@POSIX_SHELL
def test_update_shell_failure_names_recovery(tmp_path, monkeypatch):
    from yoke_contracts import shell_startup_files as path_state_contract

    def fail(*args):
        raise OSError("permission denied")

    monkeypatch.setattr(path_state_contract, "_write_path_file", fail)
    with pytest.raises(
        OSError, match="shell_path_write_failed: zsh startup file .*yoke path fix"
    ):
        doctor.update_shell(env={"SHELL": "/bin/zsh", "HOME": str(tmp_path)})


@pytest.fixture
def deny_startup_access(monkeypatch):
    def deny(paths, methods=("lstat", "read_bytes")):
        for method in methods:
            original = getattr(Path, method)

            def guarded(path, *args, _original=original, **kwargs):
                if path in paths:
                    raise PermissionError(errno.EPERM, os.strerror(errno.EPERM))
                return _original(path, *args, **kwargs)

            monkeypatch.setattr(Path, method, guarded)

    return deny


@POSIX_SHELL
@pytest.mark.parametrize("methods", [("lstat", "read_bytes"), ("read_bytes",)])
def test_repair_skips_inaccessible_zprofile(tmp_path, deny_startup_access, methods):
    zprofile = tmp_path / ".zprofile"
    original = b"# user configuration\n"
    zprofile.write_bytes(original)
    (tmp_path / ".zshenv").touch()
    (tmp_path / ".bash_profile").touch()
    read_bytes = Path.read_bytes
    deny_startup_access({zprofile}, methods)

    output = doctor.update_shell(env={"HOME": str(tmp_path), "SHELL": "/bin/zsh"})

    assert f"shell_path_file_skipped: zsh startup file {zprofile}" in output
    assert f"Yoke PATH block is in {tmp_path / '.zshenv'}" in output
    assert read_bytes(zprofile) == original
    directory = shlex.quote(str(tmp_path / ".local/bin"))
    block = (
        f'{doctor.MANAGED_BEGIN}\ncase ":$PATH:" in\n    *:{directory}:*) ;;\n'
        f'    *) export PATH={directory}:"$PATH" ;;\nesac\n{doctor.MANAGED_END}\n'
    )
    for name in (".zshenv", ".bash_profile", ".bashrc"):
        assert (tmp_path / name).read_text().startswith(block)
    fish = tmp_path / ".config/fish/config.fish"
    assert fish.read_text().startswith(
        f"{doctor.MANAGED_BEGIN}\nif not contains -- {directory} $PATH\n"
        f"    set -gx PATH {directory} $PATH\nend\n{doctor.MANAGED_END}\n"
    )


@POSIX_SHELL
def test_repair_fails_if_both_zsh_startup_files_are_inaccessible(tmp_path, deny_startup_access):
    deny_startup_access({tmp_path / ".zshenv", tmp_path / ".zprofile"})
    with pytest.raises(OSError, match="shell_path_write_failed: zsh startup file"):
        doctor.update_shell(env={"HOME": str(tmp_path), "SHELL": "/bin/zsh"})
    assert (tmp_path / ".bashrc").is_file()


@POSIX_SHELL
def test_repair_requires_fish_config_only_for_fish_user(tmp_path, deny_startup_access):
    fish = tmp_path / ".config/fish/config.fish"
    deny_startup_access({fish})
    env = {"HOME": str(tmp_path), "SHELL": "/bin/zsh"}
    assert f"shell_path_file_skipped: fish startup file {fish}" in doctor.update_shell(env=env)
    with pytest.raises(OSError, match="shell_path_write_failed: fish startup file"):
        doctor.update_shell(env={**env, "SHELL": "/bin/fish"})


@POSIX_SHELL
def test_inaccessible_bash_login_probe_is_reported_per_file(tmp_path, deny_startup_access):
    profile = tmp_path / ".bash_profile"
    deny_startup_access({profile}, ("stat", "lstat", "read_bytes"))
    output = doctor.update_shell(env={"HOME": str(tmp_path), "SHELL": "/bin/bash"})
    assert f"shell_path_file_skipped: bash startup file {profile}" in output
    assert f"Yoke PATH block is in {tmp_path / '.bashrc'}" in output


def test_default_startup_file_per_shell(tmp_path):
    assert doctor.default_startup_file("zsh", tmp_path) == tmp_path / ".zprofile"
    assert doctor.default_startup_file("bash", tmp_path) == tmp_path / ".profile"
    assert (
        doctor.default_startup_file("fish", tmp_path)
        == tmp_path / ".config/fish/config.fish"
    )
    assert doctor.default_ssh_startup_file("zsh", tmp_path) == tmp_path / ".zshenv"
    assert doctor.default_ssh_startup_file("bash", tmp_path) == tmp_path / ".bashrc"
    assert doctor.startup_files_for_shell("zsh", tmp_path) == (
        tmp_path / ".zprofile",
        tmp_path / ".zshenv",
        tmp_path / ".zshrc",
        tmp_path / ".zlogin",
    )


@POSIX_SHELL
def test_path_state_contract_closes_xdg_tools_markers_and_startup_files(tmp_path):
    tool_dir = tmp_path / "xdg-bin"
    contract = doctor.resolve_path_state_contract(target="posix",
        env={
            "HOME": str(tmp_path),
            "SHELL": "/bin/bash",
            "XDG_BIN_HOME": str(tool_dir),
        }
    )

    assert contract.home == str(tmp_path)
    assert contract.shell == "bash"
    assert contract.shell_path == "/bin/bash"
    assert contract.tool_bin_dir == str(tool_dir)
    assert contract.startup_file == str(tmp_path / ".profile")
    assert contract.ssh_startup_file == str(tmp_path / ".bashrc")
    assert contract.managed_begin == doctor.MANAGED_BEGIN
    assert contract.managed_end == doctor.MANAGED_END
    assert contract.tools == doctor.TOOLS
    assert contract.harness_clis == doctor.HARNESS_CLIS
    assert contract.yoke_bin == str(tool_dir / "yoke")
    assert contract.tool_paths == tuple(str(tool_dir / tool) for tool in doctor.TOOLS)
    assert contract.supported_startup_files == tuple(
        str(path) for path in doctor.supported_startup_files(tmp_path)
    )


@POSIX_SHELL
def test_diagnose_reports_off_path(tmp_path, monkeypatch):
    monkeypatch.setattr(
        doctor,
        "verify_fresh_login",
        lambda shell=None, **_: [doctor.ToolResolution(t, None) for t in doctor.TOOLS],
    )
    monkeypatch.setattr(
        doctor,
        "verify_ssh_command",
        lambda shell=None, **_: [doctor.ToolResolution(t, None) for t in doctor.TOOLS],
    )
    env = {"PATH": "/usr/bin", "HOME": str(tmp_path), "SHELL": "/bin/zsh"}
    diag = doctor.diagnose(env=env, home=tmp_path)
    assert diag.current_on_path is False
    assert diag.tool_bin_dir == str(tmp_path / ".local" / "bin")
    assert diag.needs_fix is True
    assert diag.ssh_needs_fix is True


@POSIX_SHELL
def test_diagnose_ignores_installer_prepended_path(tmp_path, monkeypatch):
    tool_dir = tmp_path / ".local" / "bin"
    tool_dir.mkdir(parents=True)
    observed_probe_env: dict[str, str] = {}

    seeded_homes: list[tuple[str, str]] = []

    def fake_run(
        command, *, capture_output, text, timeout, env, stdin, start_new_session
    ):
        del capture_output, text, timeout
        # An interactive login shell must not inherit setup's terminal.
        assert stdin is subprocess.DEVNULL and start_new_session is True
        observed_probe_env.update(env)
        seeded_homes.append((env["HOME"], env.get("ZDOTDIR", env["HOME"])))
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(doctor.subprocess, "run", fake_run)

    env = {
        "PATH": f"{tool_dir}:/usr/bin:/bin",
        "HOME": str(tmp_path),
        "SHELL": "/bin/zsh",
    }
    diag = doctor.diagnose(env=env, home=tmp_path)

    assert diag.current_on_path is True
    assert str(tool_dir) not in observed_probe_env["PATH"].split(":")
    assert diag.needs_fix is True
    assert seeded_homes
    assert all(
        home == str(tmp_path) and home == zdotdir for home, zdotdir in seeded_homes
    )


@POSIX_SHELL
def test_diagnose_reports_yoke_shadowing(tmp_path, monkeypatch):
    tool_dir = tmp_path / ".local" / "bin"
    other_dir = tmp_path / "other" / "bin"
    tool_dir.mkdir(parents=True)
    other_dir.mkdir(parents=True)
    for path in (tool_dir / "yoke", other_dir / "yoke", tool_dir / "uv"):
        path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        path.chmod(0o755)
    monkeypatch.setattr(
        doctor,
        "verify_fresh_login",
        lambda shell=None, **_: [
            doctor.ToolResolution("uv", str(tool_dir / "uv")),
            doctor.ToolResolution("uvx", None),
            doctor.ToolResolution("yoke", str(other_dir / "yoke")),
        ],
    )
    monkeypatch.setattr(
        doctor,
        "verify_ssh_command",
        lambda shell=None, **_: [
            doctor.ToolResolution("uv", str(tool_dir / "uv")),
            doctor.ToolResolution("uvx", None),
            doctor.ToolResolution("yoke", str(tool_dir / "yoke")),
        ],
    )
    env = {
        "PATH": os.pathsep.join([str(other_dir), str(tool_dir), "/usr/bin"]),
        "HOME": str(tmp_path),
        "SHELL": "/bin/zsh",
    }

    diag = doctor.diagnose(env=env, home=tmp_path)

    assert diag.preferred_yoke_path == str(tool_dir / "yoke")
    assert diag.yoke_shadowed_by == str(other_dir / "yoke")
    assert diag.future_yoke_shadowed_by == str(other_dir / "yoke")
    assert diag.needs_fix is True


@pytest.mark.macos_only(reason="runs macOS zsh login startup files with the system shell")
def test_fresh_login_probe_observes_operator_rc(tmp_path):
    zsh = "/bin/zsh"
    operator = tmp_path / "operator"
    operator.mkdir()
    sentinel = tmp_path / "operator-rc-sourced"
    for name in (".zshenv", ".zprofile", ".zshrc", ".zlogin"):
        (operator / name).write_text(f'printf sourced >> "{sentinel}"\n')
    tool_dir = tmp_path / "xdg-bin"
    tool_dir.mkdir()
    yoke = tool_dir / "yoke"
    yoke.write_text("#!/bin/sh\nexit 0\n")
    yoke.chmod(0o755)
    env = {
        "HOME": str(operator),
        "ZDOTDIR": str(operator),
        "SHELL": zsh,
        "PATH": "/usr/bin:/bin",
        "XDG_BIN_HOME": str(tool_dir),
    }

    login = doctor.verify_fresh_login(
        "zsh", env=env, managed_path_dirs=(str(tool_dir),)
    )
    ssh = doctor.verify_ssh_command("zsh", env=env, managed_path_dirs=(str(tool_dir),))

    assert sentinel.exists()
    assert {row.name: row.path for row in login}["yoke"] is None
    assert {row.name: row.path for row in ssh}["yoke"] is None


@POSIX_SHELL
def test_ssh_probe_reads_bashrc_like_sshd(tmp_path):
    bash = shutil.which("bash")
    if not bash:
        pytest.skip("bash is required to exercise the ssh command probe")
    home = tmp_path / "home"
    home.mkdir()
    tool_dir = tmp_path / "xdg-bin"
    tool_dir.mkdir()
    yoke = tool_dir / "yoke"
    yoke.write_text("#!/bin/sh\nexit 0\n")
    yoke.chmod(0o755)
    (home / ".bashrc").write_text(f'export PATH="{tool_dir}:$PATH"\n')
    env = {
        "HOME": str(home),
        "SHELL": bash,
        "SHLVL": "1",
        "PATH": "/usr/bin:/bin",
        "XDG_BIN_HOME": str(tool_dir),
    }

    diag = doctor.diagnose(env=env, home=home)

    assert diag.ssh_startup_file == str(home / ".bashrc")
    assert {row.name: row.path for row in diag.ssh_resolved}["yoke"] == str(yoke)
    assert diag.ssh_needs_fix is False


def test_path_check_json_is_parseable(capsys):
    result = cli.path_check(["--json"])
    payload = json.loads(capsys.readouterr().out)
    assert result == (1 if payload["needs_fix"] else 0)
    assert "needs_fix" in payload
    assert "current_resolved" in payload


def test_top_level_help_teaches_concrete_path_commands(capsys):
    assert yoke_main(["--help"]) == 0
    assert "yoke path " in capsys.readouterr().out
    assert yoke_main(["path", "--help"]) == 0
    out = capsys.readouterr().out

    assert "yoke path <check|fix|verify>" not in out
    for command in ("yoke path check", "yoke path fix", "yoke path verify"):
        assert command in out


def test_path_help_recipes_resolve_in_teaching_audit(tmp_path):
    audit = generate_teaching_audit(repo_root=tmp_path, include_help=True)
    rows = [
        row
        for row in audit.surfaces
        if row.source == "yoke --help" and row.recipe.startswith("yoke path ")
    ]

    assert {row.command_form for row in rows} == {
        "yoke path check",
        "yoke path fix",
        "yoke path verify",
    }
    assert all(row.drift_type is None for row in rows)
