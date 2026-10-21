"""Observed shell configuration and fixture reset roster for uv tools."""

from __future__ import annotations

import os
import re
import shlex
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Mapping

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
        path_type = PurePosixPath if self.posix_paths else Path
        expected = tuple(
            str(path_type(self.tool_bin_dir) / tool) for tool in self.tools
        )
        if self.tool_paths != expected or self.yoke_bin != str(
            path_type(self.tool_bin_dir) / "yoke"
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
    name = Path(environ.get("SHELL") or "").name
    return name or "zsh"


def default_startup_file(shell: str, home: Path) -> Path:
    if shell == "zsh":
        return home / ".zprofile"
    if shell == "bash":
        return next(
            (
                home / name
                for name in (".bash_profile", ".bash_login", ".profile")
                if (home / name).exists()
            ),
            home / ".profile",
        )
    if shell == "fish":
        return home / ".config" / "fish" / "config.fish"
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
        # reset roster for shell configuration:
        # handwritten tool-bin PATH traces in either file change the exact
        # fresh-login branch the installer campaign proves.
        files.extend((home / ".zshrc", home / ".zlogin"))
    if shell == "bash":
        files.extend(
            home / name for name in (".bash_profile", ".bash_login", ".profile")
        )
    return tuple(dict.fromkeys(files))


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
    requested_home = environ.get("HOME") or str(Path.home())
    home_path = home or Path(requested_home)
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
        supported_startup_files=tuple(
            str(path) for path in supported_startup_files(home_path)
        ),
        managed_begin=MANAGED_BEGIN,
        managed_end=MANAGED_END,
        tools=TOOLS,
        harness_clis=HARNESS_CLIS,
        tool_paths=tuple(str(Path(bindir) / tool) for tool in TOOLS),
        yoke_bin=str(Path(bindir) / "yoke"),
        posix_paths=False,
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


def shell_setup_files(env: Mapping[str, str]) -> dict[Path, str]:
    """Use the same shell roster for setup, verification receipts and cleanup."""
    home = Path(env.get("HOME") or str(Path.home()))
    zdot = Path(env.get("ZDOTDIR") or home)
    fish = Path(env.get("XDG_CONFIG_HOME") or home / ".config")
    return {
        zdot / ".zshenv": "zsh",
        zdot / ".zprofile": "zsh",
        default_startup_file("bash", home): "bash",
        home / ".bashrc": "bash",
        fish / "fish" / "config.fish": "fish",
    }


def _without_owned_path(text: str) -> str:
    if text.count(MANAGED_BEGIN) != text.count(MANAGED_END):
        raise OSError(
            "shell_path_block_incomplete: restore the matching Yoke PATH markers "
            "in the named shell file, then retry yoke path fix or uninstall."
        )
    result = re.sub(
        rf"(?m)^{re.escape(MANAGED_BEGIN)}\n.*?^{re.escape(MANAGED_END)}\n?",
        "",
        text,
        flags=re.DOTALL,
    )
    if MANAGED_BEGIN in result or MANAGED_END in result:
        raise OSError(
            "shell_path_block_invalid: repair Yoke PATH marker order and retry."
        )
    return result


def write_shell_path(*, env: Mapping[str, str]) -> list[str]:
    """Prepend owned PATH blocks before interactive-only startup guards."""
    directory = shlex.quote(tool_bin_dir(env))
    changed = []
    for path, shell in shell_setup_files(env).items():
        try:
            original = path.read_bytes().decode("utf-8") if path.exists() else ""
            if shell == "fish":
                body = f"if not contains -- {directory} $PATH\n    set -gx PATH {directory} $PATH\nend\n"
            else:
                body = (
                    f'case ":$PATH:" in\n    *:{directory}:*) ;;\n'
                    f'    *) export PATH={directory}:"$PATH" ;;\nesac\n'
                )
            text = f"{MANAGED_BEGIN}\n{body}{MANAGED_END}\n" + _without_owned_path(
                original
            )
            if text != original:
                path.parent.mkdir(parents=True, exist_ok=True)
                # Resolve a user-owned symlink instead of replacing the link.
                _write_path_file(path, text)
                changed.append(str(path))
        except (OSError, UnicodeError) as exc:
            raise OSError(
                f"shell_path_write_failed: {path}: {exc}; check shell-file "
                "permissions and retry `yoke path fix --yes`."
            ) from exc
    return changed


def remove_shell_path(*, env: Mapping[str, str] | None = None) -> list[str]:
    """Remove owned blocks in every supported file, preserving other bytes."""
    environ = dict(os.environ if env is None else env)
    home = Path(environ.get("HOME") or str(Path.home()))
    candidates = set(supported_startup_files(home)) | set(shell_setup_files(environ))
    changed = []
    for path in sorted(candidates):
        try:
            if not path.exists():
                continue
            original = path.read_bytes().decode("utf-8")
            text = _without_owned_path(original)
            if text != original:
                _write_path_file(path, text)
                changed.append(str(path))
        except (OSError, UnicodeError) as exc:
            raise OSError(
                f"shell_path_cleanup_failed: {path}: {exc}; check the owned PATH "
                "markers and file permissions, then retry uninstall."
            ) from exc
    return changed


def _write_path_file(path: Path, text: str) -> None:
    target = path.resolve()
    mode = stat.S_IMODE(target.stat().st_mode) if target.exists() else 0o644
    descriptor, name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(text.encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
