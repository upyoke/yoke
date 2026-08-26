"""Product-owned shell and startup-file contract for Yoke's tool directory."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from yoke_contracts.harness_cli_manifest import harness_cli_executables


# Marker text is a product contract used by reset and idempotent repair.
# Do not reword it without updating both consumers.
MANAGED_BEGIN = "# >>> BEGIN YOKE MANAGED PATH >>>"
MANAGED_END = "# <<< END YOKE MANAGED PATH <<<"

TOOLS = ("uv", "uvx", "yoke")
HARNESS_CLIS = harness_cli_executables()
PATH_TOOLS = (*TOOLS, *HARNESS_CLIS)
SUPPORTED_SHELLS = ("zsh", "bash")


@dataclass(frozen=True)
class PathStateContract:
    home: str
    shell: str
    shell_path: str
    tool_bin_dir: str
    startup_file: str
    ssh_startup_file: str | None
    supported_startup_files: tuple[str, ...]
    managed_begin: str
    managed_end: str
    tools: tuple[str, ...]
    harness_clis: tuple[str, ...]
    tool_paths: tuple[str, ...]
    yoke_bin: str

    def __post_init__(self) -> None:
        expected = tuple(str(Path(self.tool_bin_dir) / tool) for tool in self.tools)
        if self.tool_paths != expected or self.yoke_bin != str(
            Path(self.tool_bin_dir) / "yoke"
        ):
            raise ValueError("PATH contract tool paths differ from product authority")
        if self.harness_clis != HARNESS_CLIS:
            raise ValueError(
                "PATH contract harness CLIs differ from manifest authority"
            )


def tool_bin_dir(env: Mapping[str, str] | None = None) -> str:
    environ = os.environ if env is None else env
    xdg = environ.get("XDG_BIN_HOME")
    if xdg:
        return xdg
    home = environ.get("HOME") or str(Path.home())
    return str(Path(home) / ".local" / "bin")


def current_shell(env: Mapping[str, str] | None = None) -> str:
    environ = os.environ if env is None else env
    name = Path(environ.get("SHELL") or "").name
    return name or "zsh"


def default_startup_file(shell: str, home: Path) -> Path:
    if shell == "zsh":
        return home / ".zprofile"
    if shell == "bash":
        return home / ".bash_profile"
    return home / ".profile"


def default_ssh_startup_file(shell: str, home: Path) -> Path | None:
    if shell == "zsh":
        return home / ".zshenv"
    if shell == "bash":
        return home / ".bashrc"
    return None


def startup_files_for_shell(shell: str, home: Path) -> tuple[Path, ...]:
    login = default_startup_file(shell, home)
    ssh = default_ssh_startup_file(shell, home)
    files = [login] if ssh is None else [login, ssh]
    if shell == "zsh":
        # A login-interactive zsh also reads both files. They must share the
        # reset roster even though Yoke writes its managed block elsewhere:
        # handwritten tool-bin PATH traces in either file change the exact
        # fresh-login branch the installer campaign proves.
        files.extend((home / ".zshrc", home / ".zlogin"))
    return tuple(files)


def supported_startup_files(home: Path) -> tuple[Path, ...]:
    candidates = [
        path
        for shell in SUPPORTED_SHELLS
        for path in startup_files_for_shell(shell, home)
    ]
    candidates.append(default_startup_file("", home))
    return tuple(dict.fromkeys(candidates))


def resolve_path_state_contract(
    *,
    env: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> PathStateContract:
    environ = dict(os.environ if env is None else env)
    home_path = home or Path(environ.get("HOME") or str(Path.home()))
    environ["HOME"] = str(home_path)
    shell = current_shell(environ)
    bindir = tool_bin_dir(environ)
    ssh_startup = default_ssh_startup_file(shell, home_path)
    return PathStateContract(
        home=str(home_path),
        shell=shell,
        shell_path=environ.get("SHELL") or f"/bin/{shell}",
        tool_bin_dir=bindir,
        startup_file=str(default_startup_file(shell, home_path)),
        ssh_startup_file=str(ssh_startup) if ssh_startup is not None else None,
        supported_startup_files=tuple(map(str, supported_startup_files(home_path))),
        managed_begin=MANAGED_BEGIN,
        managed_end=MANAGED_END,
        tools=TOOLS,
        harness_clis=HARNESS_CLIS,
        tool_paths=tuple(str(Path(bindir) / tool) for tool in TOOLS),
        yoke_bin=str(Path(bindir) / "yoke"),
    )


__all__ = [
    "HARNESS_CLIS",
    "MANAGED_BEGIN",
    "MANAGED_END",
    "PATH_TOOLS",
    "SUPPORTED_SHELLS",
    "TOOLS",
    "PathStateContract",
    "current_shell",
    "default_ssh_startup_file",
    "default_startup_file",
    "resolve_path_state_contract",
    "startup_files_for_shell",
    "supported_startup_files",
    "tool_bin_dir",
]
