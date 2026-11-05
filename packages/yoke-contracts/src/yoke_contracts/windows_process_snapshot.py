"""Read a native Windows process creation token without sending it a signal."""

from __future__ import annotations

import ctypes
from ctypes import wintypes

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
SYNCHRONIZE = 0x00100000
WAIT_TIMEOUT = 258


def _kernel32():
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    api.OpenProcess.restype = wintypes.HANDLE
    api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    api.WaitForSingleObject.restype = wintypes.DWORD
    api.GetProcessTimes.argtypes = [
        wintypes.HANDLE,
        *([ctypes.POINTER(wintypes.FILETIME)] * 4),
    ]
    api.GetProcessTimes.restype = wintypes.BOOL
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    api.CloseHandle.restype = wintypes.BOOL
    return api


def process_start_time(pid: int, *, api=None) -> str | None:
    """Return a live process's immutable creation time; absent processes return None."""
    if pid <= 0:
        return None
    api = _kernel32() if api is None else api
    handle = api.OpenProcess(
        PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, False, pid
    )
    if not handle:
        return None
    try:
        if api.WaitForSingleObject(handle, 0) != WAIT_TIMEOUT:
            return None
        creation, exited, kernel, user = (wintypes.FILETIME() for _ in range(4))
        if not api.GetProcessTimes(
            handle,
            ctypes.byref(creation),
            ctypes.byref(exited),
            ctypes.byref(kernel),
            ctypes.byref(user),
        ):
            return None
        return str((creation.dwHighDateTime << 32) | creation.dwLowDateTime)
    finally:
        api.CloseHandle(handle)
