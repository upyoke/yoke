"""Non-login hook shell command coverage."""

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

from yoke_harness.hooks.shell_command import hook_shell_command


def test_hook_shell_avoids_startup_files_and_sets_launcher_path(tmp_path: Path) -> None:
    launcher_bin = tmp_path / "launcher-bin"
    launcher_bin.mkdir()
    launcher = launcher_bin / "yoke"
    launcher.write_text("#!/bin/sh\nprintf '%s' \"$1\"\n", encoding="utf-8")
    launcher.chmod(0o755)
    command = hook_shell_command("yoke hook-ok")
    argv = shlex.split(command)

    assert argv[:2] == ["/bin/sh", "-c"]
    assert "/bin/zsh" not in command
    assert " -l" not in command
    assert "${XDG_BIN_HOME:-$HOME/.local/bin}" in command
    assert "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin" in command
    completed = subprocess.run(
        argv,
        env={
            "HOME": str(tmp_path),
            "XDG_BIN_HOME": str(launcher_bin),
            "PATH": "/bin",
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0
    assert completed.stdout == "hook-ok"


def test_hook_shell_rejects_unquoted_source() -> None:
    try:
        hook_shell_command("printf 'unsafe'")
    except ValueError as exc:
        assert "single quote" in str(exc)
    else:
        raise AssertionError("single-quoted hook source was accepted")
