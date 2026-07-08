"""Tests for the PATH doctor module and the `yoke path` CLI adapters."""

from __future__ import annotations

import json
import subprocess
import os

from yoke_cli.commands.adapters import path_doctor as cli
from yoke_cli.config import path_doctor as doctor


def test_render_block_has_markers_and_dir():
    block = doctor.render_managed_block("/home/u/.local/bin")
    assert doctor.MANAGED_BEGIN in block
    assert doctor.MANAGED_END in block
    assert "/home/u/.local/bin" in block


def test_apply_fix_creates_and_is_idempotent(tmp_path):
    target = tmp_path / ".zprofile"
    assert doctor.apply_fix(target, "/home/u/.local/bin") is True
    assert target.exists()
    before = target.read_bytes()
    # A second consecutive call is a no-op.
    assert doctor.apply_fix(target, "/home/u/.local/bin") is False
    assert target.read_bytes() == before
    assert target.read_text().count(doctor.MANAGED_BEGIN) == 1


def test_apply_fix_preserves_user_content(tmp_path):
    target = tmp_path / ".zprofile"
    target.write_text("export FOO=1\n")
    doctor.apply_fix(target, "/opt/bin")
    text = target.read_text()
    assert "export FOO=1" in text
    assert text.count(doctor.MANAGED_BEGIN) == 1


def test_apply_fix_replaces_old_block(tmp_path):
    target = tmp_path / ".zprofile"
    doctor.apply_fix(target, "/old/bin")
    doctor.apply_fix(target, "/new/bin")
    text = target.read_text()
    assert text.count(doctor.MANAGED_BEGIN) == 1
    assert "/new/bin" in text
    assert "/old/bin" not in text


def test_managed_block_moves_tool_bin_to_front_without_duplicates(tmp_path):
    block = doctor.render_managed_block(str(tmp_path / ".local" / "bin"))
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

    def fake_run(command, *, capture_output, text, timeout, env):
        del capture_output, text, timeout
        observed_probe_env.update(env)
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
