"""Shared transport double for dedicated Test Mac reset tests."""

from __future__ import annotations

import shlex
import shutil
import subprocess
from types import SimpleNamespace

from yoke_core.domain.ssh_mac_full_reset_contract import (
    FULL_RESET_MARKER,
    FULL_RESET_REMOTE_PATH,
    RESET_LOAD_AVERAGE_PREFIX,
    RESET_PROCESS_REAPED_PREFIX,
    RESET_RESTORED_ENTRIES_PREFIX,
)

GOLDEN_BASELINE_PATH = "/Users/Shared/yoke-golden/tester-home"


class FakeResetTransport:
    def __init__(self, stdout: str, *, reset_returncode: int = 0) -> None:
        self.stdout = stdout
        self.reset_returncode = reset_returncode
        self.uploads: dict[str, str] = {}
        self.commands: list[tuple[str, int]] = []
        self.cleanup_returncode = 0

    def upload(self, path: str, content: str) -> None:
        self.uploads[path] = content

    def run(self, command: str, *, timeout: int = 60):
        self.commands.append((command, timeout))
        argv = shlex.split(command)
        if argv and argv[0] == FULL_RESET_REMOTE_PATH:
            return SimpleNamespace(
                returncode=self.reset_returncode,
                stdout=self.stdout,
            )
        if argv[:3] == ["/bin/rm", "-f", "--"]:
            return SimpleNamespace(
                returncode=self.cleanup_returncode,
                stdout="",
            )
        return SimpleNamespace(returncode=0, stdout="")


def closed_reset_stdout(
    *,
    restored_entries: int = 22,
    reaped: int = 0,
    load_average: str = "1.20",
) -> str:
    """Return the four-line success receipt the restore parser accepts."""
    return "\n".join(
        (
            f"{RESET_RESTORED_ENTRIES_PREFIX}{restored_entries}",
            f"{RESET_PROCESS_REAPED_PREFIX}{reaped}",
            f"{RESET_LOAD_AVERAGE_PREFIX}{load_average}",
            FULL_RESET_MARKER,
        )
    )


def zsh_binary() -> str | None:
    """Return an available zsh interpreter for macOS-program checks."""
    return shutil.which("zsh")


def run_zsh_syntax_if_available(script: str) -> subprocess.CompletedProcess | None:
    """Syntax-check a zsh program when the current host provides zsh."""
    binary = zsh_binary()
    if binary is None:
        return None
    return subprocess.run(
        [binary, "-n"],
        input=script,
        text=True,
        capture_output=True,
        check=False,
    )


__all__ = [
    "FakeResetTransport",
    "closed_reset_stdout",
    "run_zsh_syntax_if_available",
    "zsh_binary",
]
