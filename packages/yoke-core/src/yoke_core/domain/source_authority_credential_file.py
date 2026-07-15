"""Owner-only atomic filesystem operations for source cutover credentials."""

from __future__ import annotations

import json
import os
import secrets
import stat
from pathlib import Path
from typing import Any


class SourceCredentialError(RuntimeError):
    """The local cutover credential is unsafe or does not match."""


def selected_path(path: str | Path) -> Path:
    selected = Path(path).expanduser()
    if not selected.is_absolute():
        raise SourceCredentialError("cutover credential path must be absolute")
    return selected


def write_atomic_owner_only(path: Path, payload: dict[str, Any]) -> bool:
    """Publish a new owner-only file without ever replacing a winner.

    The hard-link operation is the atomic no-clobber boundary.  A concurrent
    publisher that loses receives ``False`` and can safely load the already
    fsynced winning file.  A check followed by ``os.replace`` is deliberately
    insufficient here because two attended ``begin`` processes may overlap.
    """
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    require_owner_only_directory(path.parent)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    try:
        write_new_owner_only(temporary, payload)
        try:
            os.link(temporary, path, follow_symlinks=False)
        except FileExistsError:
            # The winner fsynced file contents before linking, but may not yet
            # have persisted the directory entry.  The loser must not load
            # and commit database state until that shared entry is durable.
            fsync_directory(path.parent)
            require_owner_only_regular(path)
            return False
        fsync_directory(path.parent)
        require_owner_only_regular(path)
        return True
    finally:
        if temporary.exists():
            temporary.unlink()
            fsync_directory(path.parent)


def replace_atomic_owner_only(path: Path, payload: dict[str, Any]) -> None:
    require_owner_only_regular(path)
    require_owner_only_directory(path.parent)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    try:
        write_new_owner_only(temporary, payload)
        os.replace(temporary, path)
        fsync_directory(path.parent)
    finally:
        if temporary.exists():
            temporary.unlink()
            fsync_directory(path.parent)
    require_owner_only_regular(path)


def write_new_owner_only(path: Path, payload: dict[str, Any]) -> None:
    raw = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "wb", closefd=True) as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def require_owner_only_regular(path: Path) -> None:
    try:
        info = path.lstat()
    except OSError as exc:
        raise SourceCredentialError("cutover credential is missing") from exc
    if (
        stat.S_ISLNK(info.st_mode)
        or not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != 0o600
    ):
        raise SourceCredentialError(
            "cutover credential must be an owner-only regular file"
        )


def require_owner_only_directory(path: Path) -> None:
    info = path.lstat()
    if (
        stat.S_ISLNK(info.st_mode)
        or not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) & 0o077
    ):
        raise SourceCredentialError(
            "cutover credential directory must be owner-only"
        )


def delete_owner_only(path: Path) -> None:
    require_owner_only_regular(path)
    path.unlink()
    fsync_directory(path.parent)


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


__all__ = [
    "SourceCredentialError", "delete_owner_only", "replace_atomic_owner_only",
    "require_owner_only_regular", "selected_path", "write_atomic_owner_only",
]
