"""Write and remove Yoke's PATH block in each supported shell startup file.

Record lines right after the block name what Yoke itself created: the
startup file, when it did not exist, and each directory made to hold it.
They sit outside the block so a CLI that rewrites only the block (an older
release after a downgrade) keeps them. Uninstall strips the block and the
records, then deletes only those recorded paths, and only while they hold
nothing else; a file that existed before keeps its own bytes, even when empty.
"""

from __future__ import annotations

import os
import re
import shlex
import stat
import sys
import tempfile
from pathlib import Path
from typing import Mapping

from yoke_contracts import shell_path_state
from yoke_contracts.shell_path_state import (
    MANAGED_BEGIN,
    MANAGED_END,
    default_startup_file,
    supported_startup_files,
)

CREATED_FILE = "# yoke created this file"
CREATED_DIR = "# yoke created directory "


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


_BLOCK = re.compile(
    rf"(?ms)^{re.escape(MANAGED_BEGIN)}\n(.*?)^{re.escape(MANAGED_END)}\n?"
)


def _without_owned_path(text: str) -> str:
    if text.count(MANAGED_BEGIN) != text.count(MANAGED_END):
        raise OSError(
            "shell_path_block_incomplete: restore the matching Yoke PATH markers "
            "in the named shell file, then retry yoke path fix or uninstall."
        )
    result = _BLOCK.sub("", text)
    if MANAGED_BEGIN in result or MANAGED_END in result:
        raise OSError(
            "shell_path_block_invalid: repair Yoke PATH marker order and retry."
        )
    return result


def _is_record(line: str) -> bool:
    return line == CREATED_FILE or line.startswith(CREATED_DIR)


def _ownership(text: str) -> list[str]:
    """The created-path records anywhere in *text*, inside a block or after it."""
    return list(dict.fromkeys(line for line in text.splitlines() if _is_record(line)))


def _without_owned(text: str) -> str:
    """*text* without Yoke's PATH block and its created-path records."""
    rest = _without_owned_path(text)
    lines = rest.splitlines(keepends=True)
    return "".join(line for line in lines if not _is_record(line.rstrip("\n")))


def _missing_dirs(path: Path) -> list[Path]:
    missing = []
    for parent in path.parents:
        if parent.exists():
            break
        missing.append(parent)
    return missing[::-1]


def write_shell_path(*, env: Mapping[str, str]) -> list[str]:
    """Prepend owned PATH blocks before interactive-only startup guards."""
    if sys.platform == "win32":
        from yoke_contracts.windows_user_path import write_user_path

        return write_user_path(shell_path_state.tool_bin_dir(env), env)
    directory = shlex.quote(shell_path_state.tool_bin_dir(env))
    changed = []
    for path, shell in shell_setup_files(env).items():
        try:
            exists = path.exists()
            original = path.read_bytes().decode("utf-8") if exists else ""
            missing = [] if exists else _missing_dirs(path)
            owned = _ownership(original) or (
                [CREATED_FILE, *(f"{CREATED_DIR}{d}" for d in missing)]
                if not exists
                else []
            )
            if shell == "fish":
                body = f"if not contains -- {directory} $PATH\n    set -gx PATH {directory} $PATH\nend\n"
            else:
                body = (
                    f'case ":$PATH:" in\n    *:{directory}:*) ;;\n'
                    f'    *) export PATH={directory}:"$PATH" ;;\nesac\n'
                )
            records = "".join(f"{line}\n" for line in owned)
            text = f"{MANAGED_BEGIN}\n{body}{MANAGED_END}\n{records}" + (
                _without_owned(original)
            )
            if text != original:
                path.parent.mkdir(parents=True, exist_ok=True)
                # Resolve a user-owned symlink instead of replacing the link.
                _write_path_file(path, text)
                changed.append(str(path))
        except (OSError, UnicodeError) as exc:
            raise OSError(
                f"shell_path_write_failed: {shell} startup file {path}: {exc}; check shell-file "
                "permissions and retry `yoke path fix --yes`."
            ) from exc
    return changed


def remove_shell_path(*, env: Mapping[str, str] | None = None) -> list[str]:
    """Remove owned blocks in every supported file, preserving other bytes.

    A file Yoke created is deleted once only its block is left, then each
    directory Yoke created for it while that directory is empty.
    """
    if sys.platform == "win32":
        # uv owns the shared bin entry. Removing it would break uv and uvx.
        return []
    environ = dict(os.environ if env is None else env)
    home = Path(environ.get("HOME") or str(Path.home()))
    candidates = set(supported_startup_files(home)) | set(shell_setup_files(environ))
    changed = []
    for path in sorted(candidates):
        try:
            if not path.exists():
                continue
            original = path.read_bytes().decode("utf-8")
            text = _without_owned(original)
            if text == original:
                continue
            owned = _ownership(original)
            if text or CREATED_FILE not in owned or path.is_symlink():
                _write_path_file(path, text)
            else:
                path.unlink()
                _remove_created_dirs(owned)
            changed.append(str(path))
        except (OSError, UnicodeError) as exc:
            raise OSError(
                f"shell_path_cleanup_failed: {path}: {exc}; check the owned PATH "
                "markers and file permissions, then retry uninstall."
            ) from exc
    return changed


def _remove_created_dirs(owned: list[str]) -> None:
    created = [
        Path(line.removeprefix(CREATED_DIR))
        for line in owned
        if line.startswith(CREATED_DIR)
    ]
    for directory in reversed(created):
        if directory.is_dir() and not directory.is_symlink() and not any(
            directory.iterdir()
        ):
            directory.rmdir()


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


__all__ = [
    "CREATED_DIR",
    "CREATED_FILE",
    "remove_shell_path",
    "shell_setup_files",
    "write_shell_path",
]
