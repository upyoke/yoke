"""Windows ownership and directory write-access checks, allowing shared reads."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import stat

if __package__:
    from yoke_contracts import windows_private_directory as private
else:
    import _yoke_windows_private_directory as private

# File write/append, extended attributes, delete-child, attributes, DELETE,
# WRITE_DAC, WRITE_OWNER, GENERIC_WRITE and GENERIC_ALL.
_WRITE_ACCESS = 0x00000156 | 0x000D0000 | 0x50000000
_INHERIT_ONLY_ACE = 0x08
_ALLOW_ACE_TYPES = {0x00, 0x05, 0x09, 0x0B}
_DENY_ACE_TYPES = {0x01, 0x06, 0x0A, 0x0C}
_OBJECT_ACE_TYPES = {0x05, 0x0B}


class _Acl(ctypes.Structure):
    _fields_ = [("revision", ctypes.c_ubyte), ("reserved", ctypes.c_ubyte),
                ("size", ctypes.c_uint16), ("count", ctypes.c_uint16),
                ("reserved2", ctypes.c_uint16)]


class _AceHeader(ctypes.Structure):
    _fields_ = [("kind", ctypes.c_ubyte), ("flags", ctypes.c_ubyte),
                ("size", ctypes.c_uint16)]


def is_current_user_owned_path(path: str | Path) -> bool:
    """Check the token user's owner SID without imposing an access policy."""
    return _inspect(path, check_writes=False)


def is_others_unwritable_directory(path: str | Path) -> bool:
    """Require current-user ownership and no effective foreign write grant."""
    return _inspect(path, check_writes=True)


def _inspect(path: str | Path, *, check_writes: bool) -> bool:
    if os.name != "nt":
        raise OSError("Windows path ACL inspection is unavailable")
    selected = Path(path)
    info = selected.stat(follow_symlinks=False)
    if check_writes and not stat.S_ISDIR(info.st_mode):
        return False
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        return False
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    private._configure_apis(advapi, kernel)
    advapi.GetNamedSecurityInfoW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    advapi.GetAce.argtypes = [ctypes.c_void_p, wintypes.DWORD,
                             ctypes.POINTER(ctypes.c_void_p)]
    advapi.GetAce.restype = wintypes.BOOL
    dacl, owner, descriptor = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_void_p()
    try:
        result = advapi.GetNamedSecurityInfoW(
            str(selected), 1, 0x5 if check_writes else 0x1,
            ctypes.byref(owner), None, ctypes.byref(dacl) if check_writes else None,
            None, ctypes.byref(descriptor),
        )
        if result or not owner.value:
            return False
        user = private._current_user_sid(advapi, kernel)
        if private._sid_string(owner.value, advapi, kernel) != user:
            return False
        if not check_writes:
            return True
        if not dacl.value:  # A null DACL grants everyone full access.
            return False
        allowed = {user, private._OWNER_RIGHTS_SID, private._SYSTEM_SID,
                   private._ADMINISTRATORS_SID}
        return _acl_is_others_unwritable(dacl, allowed, advapi, kernel)
    finally:
        if descriptor.value:
            kernel.LocalFree(descriptor)


def _acl_is_others_unwritable(dacl, allowed: set[str], advapi, kernel) -> bool:
    acl = ctypes.cast(dacl, ctypes.POINTER(_Acl)).contents
    for index in range(acl.count):
        pointer = ctypes.c_void_p()
        if not advapi.GetAce(dacl, index, ctypes.byref(pointer)) or not pointer.value:
            return False
        header = ctypes.cast(pointer, ctypes.POINTER(_AceHeader)).contents
        if header.flags & _INHERIT_ONLY_ACE or header.kind in _DENY_ACE_TYPES:
            continue
        # Unknown DACL entries cannot establish that foreign writes are absent.
        if header.kind not in _ALLOW_ACE_TYPES or header.size < 12:
            return False
        mask = ctypes.c_uint32.from_address(pointer.value + 4).value
        if not mask & _WRITE_ACCESS:
            continue
        offset = 8
        if header.kind in _OBJECT_ACE_TYPES:
            flags = ctypes.c_uint32.from_address(pointer.value + 8).value
            if flags & ~3:
                return False
            offset = 12 + 16 * bool(flags & 1) + 16 * bool(flags & 2)
        if header.size < offset + 8:
            return False
        sid = pointer.value + offset
        if private._sid_string(sid, advapi, kernel) not in allowed:
            return False
    return True
