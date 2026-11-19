"""Observed shell configuration and fixture reset roster for uv tools."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath
from typing import Literal, Mapping

from yoke_contracts.harness_cli_manifest import harness_cli_executables


# These markers delimit only Yoke-owned PATH text for repair and uninstall.
MANAGED_BEGIN = "# >>> BEGIN YOKE MANAGED PATH >>>"
MANAGED_END = "# <<< END YOKE MANAGED PATH <<<"

TOOLS = ("uv", "uvx", "yoke")
HARNESS_CLIS = harness_cli_executables()
PATH_TOOLS = (*TOOLS, *HARNESS_CLIS)
SUPPORTED_SHELLS = ("zsh", "bash", "fish")


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
    posix_paths: bool = False

    def __post_init__(self) -> None:
        path_type = PureWindowsPath if self.shell == "windows" else PurePosixPath
        suffix = ".exe" if self.shell == "windows" else ""
        expected = tuple(
            str(
                path_type(self.tool_bin_dir)
                / (tool + (".cmd" if tool == "yoke" and suffix else suffix))
            )
            for tool in self.tools
        )
        if self.tool_paths != expected or self.yoke_bin != str(
            path_type(self.tool_bin_dir) / ("yoke.cmd" if suffix else "yoke")
        ):
            raise ValueError("PATH contract tool paths differ from product authority")
        if self.harness_clis != HARNESS_CLIS:
            raise ValueError(
                "PATH contract harness CLIs differ from manifest authority"
            )


def tool_bin_dir(env: Mapping[str, str] | None = None) -> str:
    environ = os.environ if env is None else env
    xdg = environ.get("UV_TOOL_BIN_DIR") or environ.get("XDG_BIN_HOME")
    if xdg:
        return xdg
    home = environ.get("HOME") or str(Path.home())
    return str(Path(home) / ".local" / "bin")


def current_shell(env: Mapping[str, str] | None = None) -> str:
    environ = os.environ if env is None else env
    if sys.platform == "win32":
        return "windows"
    return _posix_shell(environ)


def _posix_shell(environ: Mapping[str, str]) -> str:
    shell = environ.get("SHELL")
    if not shell:
        try:
            import pwd
            from yoke_contracts.owner_private_path import posix_uid

            shell = pwd.getpwuid(posix_uid()).pw_shell
        except (ImportError, KeyError):
            shell = ""
    return PurePosixPath(shell).name if shell else "zsh"


def default_startup_file(shell: str, home: PurePath) -> PurePath:
    if shell == "zsh":
        return home / ".zprofile"
    if shell == "bash":
        return next(
            (
                home / name
                for name in (".bash_profile", ".bash_login", ".profile")
                if isinstance(home, Path) and (home / name).exists()
            ),
            home / ".profile",
        )
    if shell == "fish":
        return home / ".config" / "fish" / "config.fish"
    return home / ".profile"


def default_ssh_startup_file(shell: str, home: PurePath) -> PurePath | None:
    if shell == "zsh":
        return home / ".zshenv"
    if shell == "bash":
        return home / ".bashrc"
    return None


def startup_files_for_shell(shell: str, home: PurePath) -> tuple[PurePath, ...]:
    login = default_startup_file(shell, home)
    ssh = default_ssh_startup_file(shell, home)
    files = [login] if ssh is None else [login, ssh]
    if shell == "zsh":
        # A login-interactive zsh also reads both files. They must share the
        # reset roster for shell configuration:
        # handwritten tool-bin PATH traces in either file change the exact
        # fresh-login branch the installer campaign proves.
        files.extend((home / ".zshrc", home / ".zlogin"))
    if shell == "bash":
        files.extend(
            home / name for name in (".bash_profile", ".bash_login", ".profile")
        )
    return tuple(dict.fromkeys(files))


def supported_startup_files(home: PurePath) -> tuple[PurePath, ...]:
    candidates = [
        path
        for shell in SUPPORTED_SHELLS
        for path in startup_files_for_shell(shell, home)
    ]
    candidates.append(default_startup_file("", home))
    return tuple(dict.fromkeys(candidates))


def resolve_path_state_contract(
    *,
    target: Literal["windows", "posix"],
    env: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> PathStateContract:
    environ = dict(os.environ if env is None else env)
    if target not in ("windows", "posix"):
        raise ValueError("PATH contract target must be windows or posix")
    windows = target == "windows"
    path_type = PureWindowsPath if windows else PurePosixPath
    requested_home = environ.get("HOME") or str(Path.home())
    home_path = home if home is not None else path_type(requested_home)
    environ["HOME"] = str(home_path)

    shell = (
        "windows"
        if windows
        else (
            _posix_shell(environ)
            if home is not None
            else PurePosixPath(environ.get("SHELL") or "/bin/zsh").name
        )
    )
    suffix = ".exe" if windows else ""
    bindir = str(
        path_type(
            environ.get("UV_TOOL_BIN_DIR")
            or environ.get("XDG_BIN_HOME")
            or home_path / ".local" / "bin"
        )
    )
    ssh_startup = default_ssh_startup_file(shell, home_path)
    return PathStateContract(
        home=str(home_path),
        shell=shell,
        shell_path=(environ.get("COMSPEC") or "cmd.exe")
        if windows
        else environ.get("SHELL") or f"/bin/{shell}",
        tool_bin_dir=bindir,
        startup_file=r"HKCU\Environment\Path"
        if windows
        else str(default_startup_file(shell, home_path)),
        ssh_startup_file=str(ssh_startup) if ssh_startup is not None else None,
        supported_startup_files=tuple(
            str(path)
            for path in (() if windows else supported_startup_files(home_path))
        ),
        managed_begin=MANAGED_BEGIN,
        managed_end=MANAGED_END,
        tools=TOOLS,
        harness_clis=HARNESS_CLIS,
        tool_paths=tuple(
            str(
                path_type(bindir)
                / (tool + (".cmd" if tool == "yoke" and suffix else suffix))
            )
            for tool in TOOLS
        ),
        yoke_bin=str(path_type(bindir) / ("yoke.cmd" if suffix else "yoke")),
        posix_paths=not windows,
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

