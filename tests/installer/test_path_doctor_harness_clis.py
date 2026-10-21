"""Regression coverage for owned shell configuration."""

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


def _update(home, shell):
    env = _env(home, shell)
    bindir = home / ".local/bin"
    bindir.mkdir(parents=True)
    yoke = bindir / "yoke"
    yoke.write_text("#!/bin/sh\nexit 0\n")
    yoke.chmod(0o755)
    doctor.update_shell(env=env)
    return env


def test_owned_path_preserves_bash_profile_and_bashrc(tmp_path, monkeypatch):
    profile = tmp_path / ".profile"
    bashrc = tmp_path / ".bashrc"
    profile.write_text("export PROFILE_KEPT=yes\n")
    bashrc.write_text("export BASHRC_KEPT=yes\n")
    env = _update(tmp_path, "bash")
    assert not (tmp_path / ".bash_profile").exists()
    assert "export PROFILE_KEPT=yes\n" in profile.read_text()
    assert "export BASHRC_KEPT=yes\n" in bashrc.read_text()
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
    before = (profile.read_bytes(), bashrc.read_bytes())
    env["PATH"] = str(tmp_path / ".local/bin") + os.pathsep + env["PATH"]
    doctor.update_shell(env=env)
    assert (profile.read_bytes(), bashrc.read_bytes()) == before


def test_owned_path_adds_tool_directory_to_fish(tmp_path, monkeypatch):
    env = _update(tmp_path, "fish")
    config = tmp_path / ".config/fish/config.fish"
    assert "set -gx PATH" in config.read_text()
    assert (tmp_path / ".zshenv").exists()
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
