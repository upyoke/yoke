"""Descriptor-based advisory shared/exclusive locks on POSIX and Windows.

filelock 3.29.4 was checked: its WindowsFileLock uses exclusive msvcrt locks;
its ReadWriteLock owns path/SQLite state, not the caller's descriptor. Neither
can preserve this API, so the Windows boundary uses LockFileEx directly.
"""
from __future__ import annotations

import os
import time

if os.name != "nt":
    import fcntl


def _windows_lock(descriptor: int, *, exclusive=False, release=False):
    import ctypes
    from ctypes import wintypes
    import msvcrt

    class Overlapped(ctypes.Structure):
        _fields_ = [("Internal", ctypes.c_size_t), ("InternalHigh", ctypes.c_size_t),
                    ("Offset", wintypes.DWORD), ("OffsetHigh", wintypes.DWORD),
                    ("hEvent", wintypes.HANDLE)]

    api = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = msvcrt.get_osfhandle(descriptor)
    overlapped = Overlapped()
    if release:
        function = api.UnlockFileEx
        function.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
                             wintypes.DWORD, ctypes.POINTER(Overlapped)]
        args = (handle, 0, 1, 0, ctypes.byref(overlapped))
    else:
        function = api.LockFileEx
        function.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
                             wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(Overlapped)]
        args = (handle, 1 | (2 if exclusive else 0), 0, 1, 0, ctypes.byref(overlapped))
    function.restype = wintypes.BOOL
    if not function(*args):
        error = ctypes.get_last_error()
        if not release and error == 33:  # ERROR_LOCK_VIOLATION
            raise BlockingIOError(11, "file_lock_contended: retry after the holder releases")
        raise OSError(error, "file_lock_failed: check descriptor access and retry")


def _acquire(descriptor: int, *, shared: bool, blocking: bool):
    if os.name != "nt":
        fcntl.flock(descriptor, (fcntl.LOCK_SH if shared else fcntl.LOCK_EX)
                    | (0 if blocking else fcntl.LOCK_NB))
        return
    while True:
        try:
            _windows_lock(descriptor, exclusive=not shared)
            return
        except BlockingIOError:
            if not blocking:
                raise
            time.sleep(0.05)


def acquire_exclusive(descriptor: int) -> None:
    """Wait for exclusive custody of the file."""
    _acquire(descriptor, shared=False, blocking=True)


def acquire_exclusive_nonblocking(descriptor: int) -> None:
    """Acquire exclusive custody, or raise BlockingIOError."""
    _acquire(descriptor, shared=False, blocking=False)


def acquire_shared(descriptor: int) -> None:
    """Wait for a shared lease; independent readers may coexist."""
    _acquire(descriptor, shared=True, blocking=True)


def acquire_shared_nonblocking(descriptor: int) -> None:
    """Acquire a shared lease, or raise BlockingIOError."""
    _acquire(descriptor, shared=True, blocking=False)


def release_exclusive(descriptor: int) -> None:
    """Release a descriptor lock (shared or exclusive)."""
    if os.name == "nt":
        _windows_lock(descriptor, release=True)
    else:
        fcntl.flock(descriptor, fcntl.LOCK_UN)


def release_shared(descriptor: int) -> None:
    """Release a shared lease."""
    release_exclusive(descriptor)


__all__ = ["acquire_exclusive", "acquire_exclusive_nonblocking", "release_exclusive",
           "acquire_shared", "acquire_shared_nonblocking", "release_shared"]
