"""Durable, serialized file operations for machine configuration."""

from __future__ import annotations

from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import stat
import tempfile
from typing import Iterator


class MachineConfigFileError(RuntimeError):
    """The machine-config file or its stable lock is unsafe."""


@contextmanager
def exclusive_lock(config_path: str | Path) -> Iterator[None]:
    """Hold the stable owner-only lock associated with ``config_path``."""
    selected = Path(config_path).expanduser()
    try:
        selected.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        _assert_secure_parent(selected.parent)
        lock_path = selected.with_name(selected.name + ".lock")
        flags = (
            os.O_RDWR | os.O_CREAT
            | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        )
        descriptor = os.open(lock_path, flags, 0o600)
    except OSError as exc:
        raise MachineConfigFileError(
            f"machine-config lock could not be opened: {selected}"
        ) from exc
    locked = False
    try:
        info = os.fstat(descriptor)
        _assert_owned_regular_file(info, lock_path)
        os.fchmod(descriptor, 0o600)
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        locked = True
        _assert_stable_lock(descriptor, lock_path)
        _assert_config_target(selected)
        yield
    except OSError as exc:
        raise MachineConfigFileError(
            f"machine-config lock failed: {selected}"
        ) from exc
    finally:
        try:
            if locked:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def atomic_write_text(path: str | Path, content: str) -> None:
    """Replace ``path`` durably with an owner-only UTF-8 document."""
    selected = Path(path).expanduser()
    descriptor = -1
    tmp_path: Path | None = None
    try:
        descriptor, raw_tmp = tempfile.mkstemp(
            prefix=f".{selected.name}.", suffix=".tmp", dir=selected.parent,
        )
        tmp_path = Path(raw_tmp)
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            descriptor = -1
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp_path, selected)
        _fsync_directory(selected.parent)
    except OSError as exc:
        raise MachineConfigFileError(
            f"machine config could not be written: {selected}"
        ) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if tmp_path is not None:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass


def remove_file(path: str | Path) -> bool:
    """Remove ``path`` durably while leaving its stable lock in place."""
    selected = Path(path).expanduser()
    try:
        selected.unlink()
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise MachineConfigFileError(
            f"machine config could not be removed: {selected}"
        ) from exc
    try:
        _fsync_directory(selected.parent)
    except OSError as exc:
        raise MachineConfigFileError(
            f"machine-config removal could not be synced: {selected}"
        ) from exc
    return True


def _assert_secure_parent(path: Path) -> None:
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode):
        raise MachineConfigFileError(
            f"machine-config parent must be a directory: {path}"
        )
    if hasattr(os, "getuid") and info.st_uid != os.getuid():
        raise MachineConfigFileError(
            f"machine-config parent is not owned by the current user: {path}"
        )
    if stat.S_IMODE(info.st_mode) & 0o022:
        raise MachineConfigFileError(
            f"machine-config parent must not be group- or world-writable: {path}"
        )


def _assert_owned_regular_file(info: os.stat_result, path: Path) -> None:
    if not stat.S_ISREG(info.st_mode):
        raise MachineConfigFileError(
            f"machine-config lock must be a regular file: {path}"
        )
    if hasattr(os, "getuid") and info.st_uid != os.getuid():
        raise MachineConfigFileError(
            f"machine-config lock is not owned by the current user: {path}"
        )
    if info.st_nlink != 1:
        raise MachineConfigFileError(
            f"machine-config lock must not have hard links: {path}"
        )


def _assert_config_target(path: Path) -> None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    if not stat.S_ISREG(info.st_mode):
        raise MachineConfigFileError(
            f"machine config must be a regular file: {path}"
        )
    if hasattr(os, "getuid") and info.st_uid != os.getuid():
        raise MachineConfigFileError(
            f"machine config is not owned by the current user: {path}"
        )


def _assert_stable_lock(descriptor: int, path: Path) -> None:
    opened = os.fstat(descriptor)
    current = path.lstat()
    if (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
        raise MachineConfigFileError(
            f"machine-config lock changed while being acquired: {path}"
        )
    if stat.S_IMODE(opened.st_mode) & 0o077:
        raise MachineConfigFileError(
            f"machine-config lock permissions must be 0600: {path}"
        )


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


__all__ = [
    "MachineConfigFileError", "atomic_write_text", "exclusive_lock",
    "remove_file",
]
