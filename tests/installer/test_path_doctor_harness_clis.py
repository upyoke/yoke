"""Regression coverage for uv-owned shell configuration."""

from __future__ import annotations
import os
from pathlib import Path
import shutil
import subprocess
from yoke_cli.config import path_doctor as doctor, path_repair_plan


def _env(home: Path, shell: str) -> dict[str, str]:
    return {
        "HOME": str(home),
        "SHELL": f"/bin/{shell}",
        "PATH": "/usr/bin:/bin",
        "XDG_CONFIG_HOME": str(home / ".config"),
        "XDG_BIN_HOME": str(home / ".local/bin"),
        "UV_TOOL_BIN_DIR": str(home / ".local/bin"),
    }


def _uv_update(home, shell, monkeypatch):
    uv = shutil.which("uv")
    assert uv, "uv is an installer prerequisite"
    env = _env(home, shell)
    original = doctor.shutil.which
    monkeypatch.setattr(
        doctor.shutil,
        "which",
        lambda name, **kw: uv if name == "uv" else original(name, **kw),
    )
    doctor.update_shell(env=env)
    return env


def test_uv_preserves_bash_profile_and_bashrc(tmp_path, monkeypatch):
    profile = tmp_path / ".profile"
    bashrc = tmp_path / ".bashrc"
    profile.write_text("export PROFILE_KEPT=yes\n")
    bashrc.write_text("export BASHRC_KEPT=yes\n")
    env = _uv_update(tmp_path, "bash", monkeypatch)
    assert not (tmp_path / ".bash_profile").exists()
    assert profile.read_text().startswith("export PROFILE_KEPT=yes\n")
    assert bashrc.read_text().startswith("export BASHRC_KEPT=yes\n")
    for file, variable in ((profile, "PROFILE_KEPT"), (bashrc, "BASHRC_KEPT")):
        result = subprocess.run(
            [
                "bash",
                "--noprofile",
                "--norc",
                "-c",
                f'. "{file}"; printf "%s\\n%s" "${variable}" "$PATH"',
            ],
            env=env,
            text=True,
            capture_output=True,
            check=True,
        )
        value, path = result.stdout.split("\n", 1)
        assert value == "yes"
        assert str(tmp_path / ".local/bin") in path.split(os.pathsep)
    monkeypatch.setattr(
        doctor,
        "verify_fresh_login",
        lambda **kw: [doctor.ToolResolution("yoke", str(tmp_path / ".local/bin/yoke"))],
    )
    before = (profile.read_bytes(), bashrc.read_bytes())
    env["PATH"] = str(tmp_path / ".local/bin") + os.pathsep + env["PATH"]
    doctor.update_shell(env=env)
    assert (profile.read_bytes(), bashrc.read_bytes()) == before


def test_uv_adds_tool_directory_to_fish(tmp_path, monkeypatch):
    env = _uv_update(tmp_path, "fish", monkeypatch)
    config = tmp_path / ".config/fish/config.fish"
    assert f'fish_add_path "{tmp_path / ".local/bin"}"' in config.read_text()
    assert not (tmp_path / ".zprofile").exists()
    fish = shutil.which("fish")
    if fish:
        env["SHELL"] = fish
        result = subprocess.run(
            [fish, "-lc", "string join : $PATH"],
            env=env,
            text=True,
            capture_output=True,
            check=True,
        )
        assert str(tmp_path / ".local/bin") in result.stdout.strip().split(":")


def test_probe_uses_fish_without_substituting_zsh(monkeypatch):
    seen = []

    def run(command, **kwargs):
        seen.append(command)
        return subprocess.CompletedProcess(command, 0, "/tmp/bin/yoke\n", "")

    monkeypatch.setattr(doctor.subprocess, "run", run)
    rows = doctor.verify_fresh_login("fish", env=_env(Path("/tmp"), "fish"))
    assert seen[0][0] == "/bin/fish"
    assert "; or true" in seen[0][2]
    assert path_repair_plan.verification_ok(rows, {})
