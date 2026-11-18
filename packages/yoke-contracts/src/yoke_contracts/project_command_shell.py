"""The shell for registered project command text, independent of the harness."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import sys

from yoke_contracts.refusal_recovery import compose_refusal


class ProjectCommandShellUnavailable(RuntimeError):
    """Project commands cannot start until their declared shell is installed."""


def project_command_shell(*, platform_name: str | None = None) -> str:
    """Use POSIX sh, or explicitly locate Git for Windows' bundled sh.

    Never select a different shell from PATH: Windows also ships unrelated
    sh commands (including WSL launchers) with different execution semantics.
    Git's cmd, bin and mingw64/bin layouts all identify its installation root.
    """
    if (platform_name or sys.platform) != "win32":
        return "/bin/sh"
    roots: list[Path] = []
    git = shutil.which("git.exe")
    if git:
        parent = Path(git).resolve().parent
        if parent.name.lower() in {"cmd", "bin"}:
            root = parent.parent
            if root.name.lower() in {"mingw64", "mingw32"}:
                root = root.parent
            roots.append(root)
    for key in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        if value := os.environ.get(key):
            roots.append(Path(value) / ("Programs/Git" if key == "LOCALAPPDATA" else "Git"))
    for root in roots:
        shell = root / "bin" / "sh.exe"
        if shell.is_file():
            return str(shell)
    raise ProjectCommandShellUnavailable(compose_refusal(
        "project_command_shell_unavailable: Git for Windows sh.exe was not found",
        recovery="Install Git for Windows from https://gitforwindows.org, "
        "add its cmd directory to PATH, then retry the project command",
    ))


__all__ = ["ProjectCommandShellUnavailable", "project_command_shell"]
