"""Cross-process advisory file locking for local Yoke state."""

from __future__ import annotations

import errno
import os
import time

if os.name == "nt":
    import msvcrt
else:
    import fcntl


def acquire_exclusive(descriptor: int) -> None:
    """Wait until an exclusive cross-process lock can be acquired."""
    if os.name != "nt":
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        return
    while True:
        try:
            acquire_exclusive_nonblocking(descriptor)
            return
        except BlockingIOError:
            time.sleep(0.05)


def acquire_exclusive_nonblocking(descriptor: int) -> None:
    """Acquire an exclusive lock or raise ``BlockingIOError`` on contention."""
    if os.name == "nt":
        _ensure_windows_lock_byte(descriptor)
        os.lseek(descriptor, 0, os.SEEK_SET)
        try:
            msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            if exc.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                raise BlockingIOError(exc.errno, exc.strerror) from exc
            raise
        return
    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)


def release_exclusive(descriptor: int) -> None:
    """Release an exclusive lock held by this descriptor."""
    if os.name == "nt":
        os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        return
    fcntl.flock(descriptor, fcntl.LOCK_UN)


def _ensure_windows_lock_byte(descriptor: int) -> None:
    """Give Windows byte-range locking a stable byte without replacing the file."""
    if os.fstat(descriptor).st_size:
        return
    os.lseek(descriptor, 0, os.SEEK_SET)
    os.write(descriptor, b"\0")


__all__ = [
    "acquire_exclusive",
    "acquire_exclusive_nonblocking",
    "release_exclusive",
]
