"""Private, bounded file operations shared by machine backup and restore."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat

from yoke_contracts import windows_private_directory
from yoke_contracts.owner_private_path import (
    create_owner_private_directory,
    is_owner_private_file,
    write_owner_private,
)

from yoke_contracts.refusal_recovery import compose_refusal


class MachineBackupError(RuntimeError):
    """A named backup refusal, safe to display without secret contents."""


def refuse(reason: str, recovery: str = "repair the named file, then retry") -> None:
    raise MachineBackupError(compose_refusal(reason, recovery=recovery))


def relative_name(raw: object) -> Path:
    if not isinstance(raw, str) or not raw:
        refuse("machine_backup_invalid_name")
    path = Path(raw)
    if path.is_absolute() or any(p in {"", ".", ".."} for p in raw.split("/")):
        refuse("machine_backup_unsafe_name", "use an unmodified backup manifest")
    return path


def no_symlinks(path: Path) -> None:
    for part in (path, *path.parents):
        if part.is_symlink():
            refuse(
                f"machine_backup_symlink: {path.name}",
                "use regular files and directories",
            )


def read_file(path: Path, name: str) -> bytes:
    no_symlinks(path)
    try:
        if not stat.S_ISREG(path.stat().st_mode):
            refuse(f"machine_backup_not_regular: {name}")
        return path.read_bytes()
    except FileNotFoundError:
        refuse(
            f"machine_backup_missing_file: {name}",
            "restore the missing backup file or create a fresh backup",
        )
    except OSError:
        refuse(f"machine_backup_unreadable: {name}")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def private_directory(path: Path, boundary: Path) -> None:
    no_symlinks(path)
    pending = []
    cursor = path
    while cursor != boundary and not cursor.exists():
        pending.append(cursor)
        cursor = cursor.parent
    for directory in reversed(pending):
        create_owner_private_directory(directory)
    cursor = path
    while cursor != boundary:
        if os.name == "nt":
            windows_private_directory.make_private_directory(cursor)
        else:
            cursor.chmod(0o700)
        cursor = cursor.parent


def write_changed(path: Path, data: bytes, *, boundary: Path) -> bool:
    no_symlinks(path)
    private_directory(path.parent, boundary)
    unchanged = path.exists() and read_file(path, path.name) == data
    if unchanged and is_owner_private_file(path):
        return False
    write_owner_private(path, data)
    return not unchanged
