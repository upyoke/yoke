"""Crash-recoverable atomic files for self-host runtime configuration."""

from __future__ import annotations

import fcntl
import os
from pathlib import Path
import stat
import tempfile


TEMPORARY_SUFFIX = ".tmp"


class AtomicFileError(RuntimeError):
    """A protected file could not be converged safely."""


def atomic_replace_bytes(target: Path, payload: bytes, *, mode: int) -> Path:
    """Serialize, recover, and durably replace one protected file."""
    directory_descriptor = -1
    lock_descriptor = -1
    descriptor = -1
    temporary_path: Path | None = None
    try:
        directory_descriptor = os.open(
            target.parent,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
        )
        lock_descriptor = _open_owner_lock(
            target,
            directory_descriptor=directory_descriptor,
        )
        fcntl.flock(lock_descriptor, fcntl.LOCK_EX)
        _cleanup_orphaned_temporaries(
            target,
            directory_descriptor=directory_descriptor,
        )

        descriptor, raw_temporary = tempfile.mkstemp(
            prefix=_temporary_prefix(target),
            suffix=TEMPORARY_SUFFIX,
            dir=target.parent,
        )
        temporary_path = Path(raw_temporary)
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb") as target_stream:
            descriptor = -1
            target_stream.write(payload)
            target_stream.flush()
            os.fsync(target_stream.fileno())
        os.replace(temporary_path, target)
        temporary_path = None
        os.fsync(directory_descriptor)
    except AtomicFileError:
        raise
    except OSError as exc:
        raise AtomicFileError(
            f"could not atomically replace protected file {target}: {exc}"
        ) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass
        if lock_descriptor >= 0:
            os.close(lock_descriptor)
        if directory_descriptor >= 0:
            os.close(directory_descriptor)
    return target


def target_lock_path(target: Path) -> Path:
    """Return the persistent advisory lock used for ``target``."""
    return target.with_name(f".{target.name}.lock")


def _open_owner_lock(target: Path, *, directory_descriptor: int) -> int:
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None or not hasattr(os, "geteuid"):
        raise AtomicFileError(
            "platform cannot safely open an owner-scoped self-host file lock"
        )
    lock_name = target_lock_path(target).name
    descriptor = -1
    created = False
    try:
        for _attempt in range(3):
            try:
                descriptor = os.open(
                    lock_name,
                    os.O_RDWR
                    | os.O_CREAT
                    | os.O_EXCL
                    | getattr(os, "O_CLOEXEC", 0)
                    | nofollow,
                    0o600,
                    dir_fd=directory_descriptor,
                )
                created = True
                break
            except FileExistsError:
                try:
                    descriptor = os.open(
                        lock_name,
                        os.O_RDWR | getattr(os, "O_CLOEXEC", 0) | nofollow,
                        dir_fd=directory_descriptor,
                    )
                    break
                except FileNotFoundError:
                    continue
        else:
            raise AtomicFileError(
                f"protected file lock changed during open: {lock_name}"
            )

        if created:
            os.fchmod(descriptor, 0o600)
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.geteuid()
            or info.st_nlink != 1
            or stat.S_IMODE(info.st_mode) & 0o077
        ):
            raise AtomicFileError(f"protected file lock is not owner-only: {lock_name}")
        return descriptor
    except Exception:
        if descriptor >= 0:
            os.close(descriptor)
        raise


def _cleanup_orphaned_temporaries(
    target: Path,
    *,
    directory_descriptor: int,
) -> None:
    prefix = _temporary_prefix(target)
    removed = False
    with os.scandir(target.parent) as entries:
        for entry in entries:
            if not (
                entry.name.startswith(prefix) and entry.name.endswith(TEMPORARY_SUFFIX)
            ):
                continue
            try:
                info = entry.stat(follow_symlinks=False)
            except FileNotFoundError:
                continue
            if not (stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid()):
                continue
            try:
                os.unlink(entry.path)
                removed = True
            except FileNotFoundError:
                pass
    if removed:
        os.fsync(directory_descriptor)


def _temporary_prefix(target: Path) -> str:
    return f".{target.name}."


__all__ = [
    "AtomicFileError",
    "TEMPORARY_SUFFIX",
    "atomic_replace_bytes",
    "target_lock_path",
]
