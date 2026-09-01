"""Shared transport double and program harness for Test Mac reset tests."""

from __future__ import annotations

import os
from pathlib import Path
import pytest
import shlex
import shutil
import subprocess
from types import SimpleNamespace

from yoke_harness.ssh_mac_full_reset_script import FULL_RESET_SCRIPT

from yoke_harness.ssh_mac_full_reset_contract import (
    FULL_RESET_MARKER,
    FULL_RESET_REMOTE_PATH,
    RESET_LOAD_AVERAGE_PREFIX,
    RESET_PROCESS_REAPED_PREFIX,
    RESET_RESTORED_ENTRIES_PREFIX,
    RESET_SELF_HOST_CONTAINERS_PREFIX,
    RESET_SELF_HOST_IMAGES_PREFIX,
    RESET_SELF_HOST_VOLUMES_PREFIX,
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
    self_host_containers: int = 0,
    self_host_volumes: int = 0,
    self_host_images: int = 0,
) -> str:
    """Return the counted success receipt the restore parser accepts."""
    return "\n".join(
        (
            f"{RESET_RESTORED_ENTRIES_PREFIX}{restored_entries}",
            f"{RESET_PROCESS_REAPED_PREFIX}{reaped}",
            f"{RESET_SELF_HOST_CONTAINERS_PREFIX}{self_host_containers}",
            f"{RESET_SELF_HOST_VOLUMES_PREFIX}{self_host_volumes}",
            f"{RESET_SELF_HOST_IMAGES_PREFIX}{self_host_images}",
            f"{RESET_LOAD_AVERAGE_PREFIX}{load_average}",
            FULL_RESET_MARKER,
        )
    )


#: The program splits into function definitions and the driver that calls
#: them. Tests exercise one function at a time against a scratch home, so they
#: load the definitions and supply the variables the driver would have set.
_DRIVER_MARKER = '\nreset_step="$reset_phase_validate_home"\n'


def function_program() -> str:
    """Return the rendered program's function definitions without its driver."""
    functions, separator, _driver = FULL_RESET_SCRIPT.partition(_DRIVER_MARKER)
    assert separator
    return functions


def assignment(name: str, value: str) -> str:
    """Render one shell assignment the driver would otherwise have made."""
    return f"{name}={shlex.quote(value)}"


def isolated_shell_env(
    shell_home: Path, env: dict[str, str] | None = None
) -> dict[str, str]:
    """Point an executed shell at a scratch home with its own startup files."""
    shell_home.mkdir(parents=True, exist_ok=True)
    for startup_file in (".zshenv", ".zprofile", ".zshrc", ".zlogin"):
        (shell_home / startup_file).touch(exist_ok=True)
    return {
        **(env or os.environ),
        "HOME": str(shell_home),
        "ZDOTDIR": str(shell_home),
    }


def run_functions(
    lines: tuple[str, ...],
    *,
    shell_home: Path,
    env: dict[str, str] | None = None,
    **kwargs,
) -> subprocess.CompletedProcess:
    """Execute program functions plus a caller-supplied driver in one shell."""
    binary = zsh_binary()
    assert binary is not None
    return subprocess.run(
        [binary, "-f"],
        input="\n".join(lines),
        text=True,
        capture_output=True,
        check=False,
        env=isolated_shell_env(shell_home, env),
        **kwargs,
    )


def require_zsh() -> str:
    """Return an interpreter, or skip: the program is macOS zsh by contract."""
    binary = zsh_binary()
    if binary is None:
        pytest.skip("zsh is required to execute the macOS reset program")
    return binary


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
    "assignment",
    "closed_reset_stdout",
    "function_program",
    "isolated_shell_env",
    "require_zsh",
    "run_functions",
    "run_zsh_syntax_if_available",
    "zsh_binary",
]
