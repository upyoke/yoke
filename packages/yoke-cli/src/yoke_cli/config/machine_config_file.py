"""Durable, serialized file operations for machine configuration."""

from __future__ import annotations

from yoke_contracts import owner_private_path
from yoke_contracts import platform_file_lock
from yoke_contracts import platform_file_sync
from yoke_contracts import windows_private_directory
from yoke_contracts.machine_config.directories import create_private_directory

from contextlib import contextmanager
import os
from pathlib import Path
import shlex
import stat
from typing import Iterator

_WINDOWS = os.name == "nt"


class MachineConfigFileError(RuntimeError):
    """The machine-config file or its stable lock is unsafe."""


def ensure_owner_only_directory(path: str | Path) -> Path:
    """Create or tighten one current-user-owned machine-state directory.

    Nested runtime writers may create their parents with the process umask
    before machine config exists.  Establish the machine-home boundary first
    so those children cannot leave it group- or world-writable.
    """
    selected = Path(path).expanduser()
    try:
        create_private_directory(selected)
        if owner_private_path.is_owner_private_directory(selected):
            return selected
        info = selected.lstat()
        if stat.S_ISLNK(info.st_mode):
            raise MachineConfigFileError(
                f"machine-state directory could not be secured: {selected} is a "
                "symbolic link; replace it with a real directory, then retry"
            )
        if not stat.S_ISDIR(info.st_mode):
            raise MachineConfigFileError(
                f"machine-state path must be a directory: {selected}"
            )
        if _WINDOWS:
            raise MachineConfigFileError(
                f"machine-state directory is not owner-only: {selected}; "
                f"{_REPAIR_WINDOWS_ACCESS}, then retry"
            )
        # POSIX only: tighten an own directory left at the umask, never a
        # foreign one (root's chmod would otherwise succeed).
        if hasattr(os, "getuid") and info.st_uid != os.getuid():
            raise MachineConfigFileError(
                f"machine-state directory is not owned by the current user: {selected}"
            )
        selected.chmod(0o700)
        if not owner_private_path.is_owner_private_directory(selected):
            raise MachineConfigFileError(
                f"machine-state directory changed while being secured: {selected}"
            )
    except MachineConfigFileError:
        raise
    except OSError as exc:
        raise MachineConfigFileError(
            f"machine-state directory could not be secured: {selected}; "
            "make sure your account owns it, then retry"
        ) from exc
    return selected


def config_lock_path(config_path: str | Path) -> Path:
    """Return the stable advisory-lock path for one machine config."""
    selected = Path(config_path).expanduser()
    return selected.with_name(selected.name + ".lock")


@contextmanager
def exclusive_lock(config_path: str | Path) -> Iterator[None]:
    """Hold the stable owner-only lock associated with ``config_path``."""
    selected = Path(config_path).expanduser()
    try:
        create_private_directory(selected.parent)
        _assert_secure_parent(selected.parent)
        lock_path = config_lock_path(selected)
        if _WINDOWS:
            try:
                descriptor = windows_private_directory.create_private_file(lock_path)
            except FileExistsError:
                # Never repair an existing lock: validate its original ACL below.
                descriptor = os.open(lock_path, os.O_RDWR | _OPEN_FLAGS)
        else:
            descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT | _OPEN_FLAGS, 0o600)
    except OSError as exc:
        raise MachineConfigFileError(
            f"machine-config lock could not be opened: {selected}"
        ) from exc
    locked = False
    try:
        _secure_lock_descriptor(descriptor, lock_path)
        platform_file_lock.acquire_exclusive(descriptor)
        locked = True
        _assert_stable_lock(descriptor, lock_path)
        _assert_config_target(selected)
        yield
    except OSError as exc:
        raise MachineConfigFileError(f"machine-config lock failed: {selected}") from exc
    finally:
        try:
            if locked:
                platform_file_lock.release_exclusive(descriptor)
        finally:
            os.close(descriptor)


def remove_idle_lock_file(lock_path: str | Path) -> bool:
    """Remove an idle stable lock without allowing split lock ownership.

    The path is unlinked while its inode is exclusively locked. A waiter that
    opened the old inode must pass the normal stable-inode check before it can
    mutate state, so a newly created lock can never authorize two writers.
    """
    selected = Path(lock_path).expanduser()
    descriptor = -1
    locked = False
    try:
        _assert_secure_parent(selected.parent)
        try:
            descriptor = os.open(selected, os.O_RDWR | _OPEN_FLAGS)
        except FileNotFoundError:
            return False
        _secure_lock_descriptor(descriptor, selected)
        try:
            platform_file_lock.acquire_exclusive_nonblocking(descriptor)
        except BlockingIOError as exc:
            raise MachineConfigFileError(
                f"machine-state lock is busy: {selected}; wait for the "
                "other Yoke operation to finish, then re-run teardown"
            ) from exc
        locked = True
        _assert_stable_lock(descriptor, selected)
        if _WINDOWS:
            # Windows cannot unlink an open file. Close first; a waiter that
            # opens it meanwhile makes the unlink a sharing violation, which
            # is reported as busy and leaves the lock with that waiter.
            platform_file_lock.release_exclusive(descriptor)
            locked = False
            os.close(descriptor)
            descriptor = -1
            try:
                selected.unlink()
            except PermissionError as exc:
                raise MachineConfigFileError(
                    f"machine-state lock is busy: {selected}; wait for the "
                    "other Yoke operation to finish, then re-run teardown"
                ) from exc
        else:
            selected.unlink()
        platform_file_sync.sync_directory(selected.parent)
        return True
    except MachineConfigFileError:
        raise
    except OSError as exc:
        raise MachineConfigFileError(
            f"machine-state lock could not be removed: {selected}; repair "
            "its ownership or permissions, then re-run teardown"
        ) from exc
    finally:
        if descriptor >= 0:
            try:
                if locked:
                    platform_file_lock.release_exclusive(descriptor)
            finally:
                os.close(descriptor)


def atomic_write_text(path: str | Path, content: str) -> None:
    """Replace ``path`` durably with an owner-only UTF-8 document."""
    selected = Path(path).expanduser()
    try:
        owner_private_path.write_owner_private(selected, content)
        platform_file_sync.sync_directory(selected.parent)
    except OSError as exc:
        raise MachineConfigFileError(
            f"machine config could not be written: {selected}; check free "
            "space and that only you can write its directory, then retry"
        ) from exc


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
        platform_file_sync.sync_directory(selected.parent)
    except OSError as exc:
        raise MachineConfigFileError(
            f"machine-config removal could not be synced: {selected}"
        ) from exc
    return True


_OPEN_FLAGS = (
    getattr(os, "O_BINARY", 0)
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_NOFOLLOW", 0)
)
_REPAIR_WINDOWS_ACCESS = (
    "remove other users' access so only your Windows account, SYSTEM and "
    "Administrators remain"
)


def _assert_secure_parent(path: Path) -> None:
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode):
        raise MachineConfigFileError(
            f"machine-config parent must be a directory: {path}"
        )
    if owner_private_path.is_owner_private_directory(path):
        return
    if _WINDOWS:
        raise MachineConfigFileError(
            f"machine-config parent is not owner-only: {path}; "
            f"{_REPAIR_WINDOWS_ACCESS}, then retry"
        )
    # POSIX admits a parent others may read but not write (for example a
    # chosen YOKE_CONFIG_FILE under ~/.config); no shared helper owns that.
    if hasattr(os, "getuid") and info.st_uid != os.getuid():
        raise MachineConfigFileError(
            f"machine-config parent is not owned by the current user: {path}"
        )
    if stat.S_IMODE(info.st_mode) & 0o022:
        raise MachineConfigFileError(
            f"machine-config parent must not be group- or world-writable: {path}; "
            f"run chmod 700 {shlex.quote(str(path))}, then retry"
        )


def _secure_lock_descriptor(descriptor: int, path: Path) -> None:
    """Tighten (POSIX) and verify an opened lock before it is used."""
    if not _WINDOWS:
        # fchmod fails for a non-owner, so a foreign lock refuses here.
        os.fchmod(descriptor, 0o600)
    info = os.fstat(descriptor)
    if not stat.S_ISREG(info.st_mode):
        raise MachineConfigFileError(
            f"machine-config lock must be a regular file: {path}"
        )
    if info.st_nlink != 1:
        raise MachineConfigFileError(
            f"machine-config lock must not have hard links: {path}"
        )
    _assert_owner_private(path, "machine-config lock")


def _assert_config_target(path: Path) -> None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    if not stat.S_ISREG(info.st_mode):
        raise MachineConfigFileError(f"machine config must be a regular file: {path}")
    # Ownership only: the next write replaces the file owner-only, and
    # `yoke status` reports looser permissions as config_permissions.
    if hasattr(os, "getuid") and info.st_uid != os.getuid():
        raise MachineConfigFileError(
            f"machine config is not owned by the current user: {path}"
        )


def _assert_owner_private(path: Path, label: str) -> None:
    if owner_private_path.is_owner_private_file(path):
        return
    repair = (
        _REPAIR_WINDOWS_ACCESS
        if _WINDOWS
        else f"run chmod 600 {shlex.quote(str(path))} as its owner"
    )
    raise MachineConfigFileError(f"{label} is not owner-only: {path}; {repair}, then retry")


def _assert_stable_lock(descriptor: int, path: Path) -> None:
    opened = os.fstat(descriptor)
    current = path.lstat()
    if (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
        raise MachineConfigFileError(
            f"machine-config lock changed while being acquired: {path}"
        )
    _assert_owner_private(path, "machine-config lock")


__all__ = [
    "MachineConfigFileError",
    "atomic_write_text",
    "config_lock_path",
    "ensure_owner_only_directory",
    "exclusive_lock",
    "remove_idle_lock_file",
    "remove_file",
]
