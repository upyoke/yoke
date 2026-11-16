"""Windows DACL validation for owner-private Yoke directories."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import stat


_SYSTEM_SID = "S-1-5-18"
_ADMINISTRATORS_SID = "S-1-5-32-544"
_OWNER_RIGHTS_SID = "S-1-3-4"
_ALLOWED_ACCESS_MODES = {1, 2}  # GRANT_ACCESS, SET_ACCESS
_TRUSTEE_IS_SID = 0
_DACL_SECURITY_INFORMATION = 0x00000004
_OWNER_SECURITY_INFORMATION = 0x00000001
_SE_DACL_PROTECTED = 0x1000
_SE_FILE_OBJECT = 1
_TOKEN_QUERY = 0x0008
_TOKEN_USER = 1
_FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400


class _Trustee(ctypes.Structure):
    pass


_Trustee._fields_ = [
    ("pMultipleTrustee", ctypes.POINTER(_Trustee)),
    ("MultipleTrusteeOperation", wintypes.DWORD),
    ("TrusteeForm", wintypes.DWORD),
    ("TrusteeType", wintypes.DWORD),
    ("ptstrName", ctypes.c_void_p),
]


class _ExplicitAccess(ctypes.Structure):
    _fields_ = [
        ("grfAccessPermissions", wintypes.DWORD),
        ("grfAccessMode", wintypes.DWORD),
        ("grfInheritance", wintypes.DWORD),
        ("Trustee", _Trustee),
    ]


class _SidAndAttributes(ctypes.Structure):
    _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD)]


def is_private_directory(path: str | Path) -> bool:
    """Return whether a Windows directory allows only its user and OS admins."""
    return _is_private_path(path, require_protected=True, require_directory=True)


def is_private_file(path: str | Path) -> bool:
    """Return whether a Windows file has only trusted explicit or inherited ACLs."""
    return _is_private_path(path, require_protected=False, require_directory=False)


def _is_private_path(
    path: str | Path,
    *,
    require_protected: bool,
    require_directory: bool,
) -> bool:
    if os.name != "nt":
        raise OSError("Windows directory ACL inspection is unavailable")
    selected = Path(path)
    info = selected.stat(follow_symlinks=False)
    expected_kind = stat.S_ISDIR if require_directory else stat.S_ISREG
    if not expected_kind(info.st_mode):
        return False
    if getattr(info, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT:
        return False
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    _configure_apis(advapi, kernel)
    dacl = ctypes.c_void_p()
    owner = ctypes.c_void_p()
    descriptor = ctypes.c_void_p()
    result = advapi.GetNamedSecurityInfoW(
        str(selected),
        _SE_FILE_OBJECT,
        _DACL_SECURITY_INFORMATION | _OWNER_SECURITY_INFORMATION,
        ctypes.byref(owner),
        None,
        ctypes.byref(dacl),
        None,
        ctypes.byref(descriptor),
    )
    if result or not dacl.value or not owner.value:
        if descriptor.value:
            kernel.LocalFree(descriptor)
        return False
    entries = ctypes.POINTER(_ExplicitAccess)()
    count = wintypes.ULONG()
    try:
        user_sid = _current_user_sid(advapi, kernel)
        control = wintypes.WORD()
        revision = wintypes.DWORD()
        if not advapi.GetSecurityDescriptorControl(
            descriptor, ctypes.byref(control), ctypes.byref(revision)
        ):
            return False
        protected = bool(control.value & _SE_DACL_PROTECTED)
        if require_protected and not protected:
            return False
        if not protected and not is_private_directory(selected.parent):
            return False
        if _sid_string(owner.value, advapi, kernel) != user_sid:
            return False
        result = advapi.GetExplicitEntriesFromAclW(
            dacl, ctypes.byref(count), ctypes.byref(entries)
        )
        if result:
            return False
        allowed = {
            user_sid,
            _OWNER_RIGHTS_SID,
            _SYSTEM_SID,
            _ADMINISTRATORS_SID,
        }
        for index in range(count.value):
            entry = entries[index]
            if entry.grfAccessMode not in _ALLOWED_ACCESS_MODES:
                continue
            trustee = entry.Trustee
            if trustee.TrusteeForm != _TRUSTEE_IS_SID or not trustee.ptstrName:
                return False
            if _sid_string(trustee.ptstrName, advapi, kernel) not in allowed:
                return False
        return True
    finally:
        if entries:
            kernel.LocalFree(entries)
        kernel.LocalFree(descriptor)


def _configure_apis(advapi: object, kernel: object) -> None:
    """Declare pointer-sized Win32 signatures before crossing the FFI boundary."""
    kernel.GetCurrentProcess.argtypes = []
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    advapi.OpenProcessToken.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    advapi.OpenProcessToken.restype = wintypes.BOOL
    advapi.GetTokenInformation.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi.GetTokenInformation.restype = wintypes.BOOL
    advapi.ConvertSidToStringSidW.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.LPWSTR),
    ]
    advapi.ConvertSidToStringSidW.restype = wintypes.BOOL
    advapi.GetNamedSecurityInfoW.restype = wintypes.DWORD
    advapi.GetSecurityDescriptorControl.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.WORD),
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi.GetSecurityDescriptorControl.restype = wintypes.BOOL
    advapi.GetExplicitEntriesFromAclW.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.ULONG),
        ctypes.POINTER(ctypes.POINTER(_ExplicitAccess)),
    ]
    advapi.GetExplicitEntriesFromAclW.restype = wintypes.DWORD


def _current_user_sid(advapi: object, kernel: object) -> str:
    token = wintypes.HANDLE()
    if not advapi.OpenProcessToken(
        kernel.GetCurrentProcess(), _TOKEN_QUERY, ctypes.byref(token)
    ):
        raise OSError(ctypes.get_last_error(), "could not open the process token")
    try:
        size = wintypes.DWORD()
        advapi.GetTokenInformation(token, _TOKEN_USER, None, 0, ctypes.byref(size))
        buffer = ctypes.create_string_buffer(size.value)
        if not advapi.GetTokenInformation(
            token, _TOKEN_USER, buffer, size, ctypes.byref(size)
        ):
            raise OSError(ctypes.get_last_error(), "could not read the process user")
        return _sid_string(_SidAndAttributes.from_buffer(buffer).Sid, advapi, kernel)
    finally:
        kernel.CloseHandle(token)


def _sid_string(sid: int, advapi: object, kernel: object) -> str:
    rendered = wintypes.LPWSTR()
    if not advapi.ConvertSidToStringSidW(sid, ctypes.byref(rendered)):
        raise OSError(ctypes.get_last_error(), "could not render a Windows SID")
    try:
        return rendered.value
    finally:
        kernel.LocalFree(rendered)


def make_private_file(path: str | Path) -> None:
    """Protect an empty temporary file before its owner writes secret bytes."""
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    _configure_apis(advapi, kernel)
    sid = _current_user_sid(advapi, kernel)
    descriptor = ctypes.c_void_p()
    convert = advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW
    convert.argtypes = [wintypes.LPCWSTR, wintypes.DWORD,
                        ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
    convert.restype = wintypes.BOOL
    set_security = advapi.SetFileSecurityW
    set_security.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p]
    set_security.restype = wintypes.BOOL
    if not convert(f"O:{sid}D:P(A;;FA;;;{sid})(A;;FA;;;SY)(A;;FA;;;BA)", 1,
                   ctypes.byref(descriptor), None):
        raise OSError("owner_private_acl_failed: cannot build DACL; check Windows account policy")
    try:
        if not set_security(str(path), _DACL_SECURITY_INFORMATION | _OWNER_SECURITY_INFORMATION | 0x80000000, descriptor):
            raise OSError("owner_private_acl_failed: cannot protect file; grant owner ACL access")
    finally:
        kernel.LocalFree(descriptor)


def create_private_directory(path: str | Path) -> None:
    """Create a directory with a protected inheritable DACL from its first instant."""
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    _configure_apis(advapi, kernel)
    sid = _current_user_sid(advapi, kernel)
    descriptor = ctypes.c_void_p()
    convert = advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW
    convert.argtypes = [wintypes.LPCWSTR, wintypes.DWORD,
                        ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
    convert.restype = wintypes.BOOL
    if not convert(f"O:{sid}D:P(A;OICI;FA;;;{sid})(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)", 1,
                   ctypes.byref(descriptor), None):
        raise OSError("owner_private_acl_failed: cannot build DACL; check Windows account policy")

    class SecurityAttributes(ctypes.Structure):
        _fields_ = [("nLength", wintypes.DWORD), ("lpSecurityDescriptor", ctypes.c_void_p),
                    ("bInheritHandle", wintypes.BOOL)]

    attributes = SecurityAttributes(ctypes.sizeof(SecurityAttributes), descriptor, False)
    create = kernel.CreateDirectoryW
    create.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(SecurityAttributes)]
    create.restype = wintypes.BOOL
    try:
        if not create(str(path), ctypes.byref(attributes)):
            error = ctypes.get_last_error()
            if error == 183:
                raise FileExistsError(str(path))
            raise OSError(error, f"owner_private_directory_create_failed: {path}; check parent access")
    finally:
        kernel.LocalFree(descriptor)


__all__ = ["is_private_directory", "is_private_file", "make_private_file",
           "create_private_directory"]
