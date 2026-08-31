"""Filesystem type reconciliation coverage for the macOS reset program."""

from __future__ import annotations

import os
from pathlib import Path
import shlex
import subprocess

import pytest

from runtime.api.domain.ssh_mac_full_reset_test_support import zsh_binary
from yoke_core.domain.ssh_mac_full_reset_script import FULL_RESET_SCRIPT


def _functions() -> str:
    functions, separator, _main = FULL_RESET_SCRIPT.partition(
        '\nreset_step="$reset_phase_validate_home"\n'
    )
    assert separator
    return functions


def _run(lines: tuple[str, ...], *, shell_home: Path) -> subprocess.CompletedProcess:
    binary = zsh_binary()
    if binary is None:
        pytest.skip("zsh is required to execute the macOS reset program")
    shell_home.mkdir(parents=True, exist_ok=True)
    return subprocess.run(
        [binary, "-f"],
        input="\n".join(lines),
        text=True,
        capture_output=True,
        check=False,
        env={**os.environ, "HOME": str(shell_home), "ZDOTDIR": str(shell_home)},
    )


def test_restore_reconciles_types_and_overwrites_live_files(
    tmp_path: Path,
) -> None:
    captured = tmp_path / "golden" / "payload"
    destination = tmp_path / "live" / "payload"
    release = captured / "releases" / "current"
    release.mkdir(parents=True)
    (release / "binary").write_text("captured\n")
    (captured / "active").symlink_to("releases/current")
    (captured / "settings").write_text("captured settings\n")

    (destination / "active").mkdir(parents=True)
    (destination / "active" / "stale").write_text("stale\n")
    (destination / "settings" / "stale").mkdir(parents=True)
    live_release = destination / "releases" / "current"
    live_release.mkdir(parents=True)
    live_binary = live_release / "binary"
    live_binary.write_text("live\n")
    live_binary.chmod(0o444)
    live_release.chmod(0o555)
    live_release.parent.chmod(0o555)
    error_log = tmp_path / "restore-errors.log"
    error_log.touch()

    result = _run(
        (
            _functions(),
            f"restore_error_log={shlex.quote(str(error_log))}",
            f"restore_entry {shlex.quote(str(captured))} "
            f"{shlex.quote(str(destination.parent))}",
        ),
        shell_home=tmp_path / "shell-home",
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert (destination / "active").is_symlink()
    assert (destination / "active").resolve() == destination / "releases" / "current"
    assert (destination / "settings").read_text() == "captured settings\n"
    assert not (destination / "active" / "stale").exists()
    assert error_log.read_text() == ""
