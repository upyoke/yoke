"""Tests for the PATH doctor module and the `yoke path` CLI adapters."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from yoke_cli.commands.adapters import path_doctor as cli
from yoke_cli.config import path_doctor as doctor
from yoke_cli.main import main as yoke_main
from yoke_cli.product_boundary_teaching import generate_teaching_audit


def test_render_block_has_markers_and_dir():
    block = doctor.render_managed_block(("/home/u/.local/bin",))
    assert doctor.MANAGED_BEGIN in block
    assert doctor.MANAGED_END in block
    assert "/home/u/.local/bin" in block


def test_apply_fix_creates_and_is_idempotent(tmp_path):
    target = tmp_path / ".zprofile"
    assert doctor.apply_fix(target, ("/home/u/.local/bin",)) is True
    assert target.exists()
    before = target.read_bytes()
    # A second consecutive call is a no-op.
    assert doctor.apply_fix(target, ("/home/u/.local/bin",)) is False
    assert target.read_bytes() == before
    assert target.read_text().count(doctor.MANAGED_BEGIN) == 1


def test_apply_fix_preserves_user_content(tmp_path):
    target = tmp_path / ".zprofile"
    target.write_text("export FOO=1\n")
    doctor.apply_fix(target, ("/opt/bin",))
    text = target.read_text()
    assert "export FOO=1" in text
    assert text.count(doctor.MANAGED_BEGIN) == 1


def test_apply_fix_replaces_old_block(tmp_path):
    target = tmp_path / ".zprofile"
    doctor.apply_fix(target, ("/old/bin",))
    doctor.apply_fix(target, ("/new/bin",))
    text = target.read_text()
    assert text.count(doctor.MANAGED_BEGIN) == 1
    assert "/new/bin" in text
    assert "/old/bin" not in text


def test_managed_block_moves_tool_bin_to_front_without_duplicates(tmp_path):
    block = doctor.render_managed_block((str(tmp_path / ".local" / "bin"),))
    script = tmp_path / "profile"
    script.write_text(
        f'PATH="/usr/bin:{tmp_path / ".local" / "bin"}:/bin";\n'
        f"{block}\n"
        'printf "%s" "$PATH"\n',
        encoding="utf-8",
    )

    result = subprocess.run(
        ["bash", str(script)],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    entries = result.stdout.split(os.pathsep)
    assert entries[0] == str(tmp_path / ".local" / "bin")
    assert entries.count(str(tmp_path / ".local" / "bin")) == 1


def test_default_startup_file_per_shell(tmp_path):
    assert doctor.default_startup_file("zsh", tmp_path) == tmp_path / ".zprofile"
    assert doctor.default_startup_file("bash", tmp_path) == tmp_path / ".bash_profile"
    assert doctor.default_startup_file("fish", tmp_path) == tmp_path / ".profile"
    assert doctor.default_ssh_startup_file("zsh", tmp_path) == tmp_path / ".zshenv"
    assert doctor.default_ssh_startup_file("bash", tmp_path) == tmp_path / ".bashrc"
    assert doctor.startup_files_for_shell("zsh", tmp_path) == (
        tmp_path / ".zprofile",
        tmp_path / ".zshenv",
        tmp_path / ".zshrc",
        tmp_path / ".zlogin",
    )


def test_path_state_contract_closes_xdg_tools_markers_and_startup_files(tmp_path):
    tool_dir = tmp_path / "xdg-bin"
    contract = doctor.resolve_path_state_contract(
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
    assert contract.startup_file == str(tmp_path / ".bash_profile")
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


def test_diagnose_ignores_installer_prepended_path(tmp_path, monkeypatch):
    tool_dir = tmp_path / ".local" / "bin"
    tool_dir.mkdir(parents=True)
    observed_probe_env: dict[str, str] = {}

    seeded_homes: list[tuple[str, str]] = []
    seeded_blocks: list[str] = []

    def fake_run(command, *, capture_output, text, timeout, env):
        del capture_output, text, timeout
        observed_probe_env.update(env)
        seeded_homes.append((env["HOME"], env["ZDOTDIR"]))
        seeded_blocks.append((Path(env["HOME"]) / ".zprofile").read_text())
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
        home != str(tmp_path) and home == zdotdir for home, zdotdir in seeded_homes
    )
    assert all(doctor.MANAGED_BEGIN in block for block in seeded_blocks)


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


def test_fresh_login_probe_does_not_source_operator_rc(tmp_path):
    zsh = shutil.which("zsh")
    if not zsh:
        pytest.skip("zsh is required to exercise login-shell isolation")
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

    assert not sentinel.exists()
    assert {row.name: row.path for row in login}["yoke"] == str(yoke)
    assert {row.name: row.path for row in ssh}["yoke"] == str(yoke)


def test_path_check_json_is_parseable(capsys):
    assert cli.path_check(["--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert "needs_fix" in payload
    assert "current_resolved" in payload


def test_path_fix_print_block_writes_nothing(capsys):
    assert cli.path_fix(["--print-block"]) == 0
    out = capsys.readouterr().out
    assert doctor.MANAGED_BEGIN in out
    assert doctor.MANAGED_END in out


def test_top_level_help_teaches_concrete_path_commands(capsys):
    assert yoke_main(["--help"]) == 0
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
