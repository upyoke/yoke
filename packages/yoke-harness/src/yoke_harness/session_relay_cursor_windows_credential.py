"""Read the Windows Cursor Agent sign-in from its default per-user DPAPI store.

Cursor Agent on Windows keeps its sign-in in ``auth.dpapi`` beside
``auth.json``: ``auth.json`` holds only the marker
``{"storedIn": "os-secret-store"}`` and ``auth.dpapi`` holds
``{"version": 1, "dpapi": "<base64>"}``, a blob protected for the current
Windows user. The relay runs as that same signed-in user, so it unprotects the
blob in-process through ``CryptUnprotectData``; the token never enters a
process argument, a log or a reading, and is used only for the Cursor usage
probe.

Only that default store is read. Cursor's opt-in Credential Locker mode
(``CURSOR_CLI_WINDOWS_CREDENTIAL_MANAGER=1``) and any other store
configuration report ``cursor_secret_store_unsupported``. A plaintext
``accessToken`` in ``auth.json`` is ignored.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
from pathlib import Path
import re
from typing import Callable, Mapping

from yoke_contracts.session_control.plan_limit_unreadable_guidance import (
    CURSOR_SECRET_STORE_MISSING_REASON,
    CURSOR_SECRET_STORE_UNSUPPORTED_REASON,
)

_STALE_REASON = "stale_credential"
_DEFAULT_STORE = "os-secret-store"
_CREDENTIAL_LOCKER_ENV = "CURSOR_CLI_WINDOWS_CREDENTIAL_MANAGER"
_STORE_FORMAT_VERSION = 1
# Bounds the read: Cursor's file is well under a kilobyte.
_MAX_FILE_BYTES = 64 * 1024
_BASE64 = re.compile(r"^[A-Za-z0-9+/]+={0,2}$")

Unprotect = Callable[[bytes], "bytes | None"]


def cursor_profile_dir(environ: Mapping[str, str]) -> Path:
    """Cursor's Windows profile directory under the user's Roaming AppData."""
    root = environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(root) / "cursor"


def _read_json(path: Path) -> object:
    with path.open("rb") as handle:
        raw = handle.read(_MAX_FILE_BYTES + 1)
    if len(raw) > _MAX_FILE_BYTES:
        raise ValueError(f"{path.name} exceeds {_MAX_FILE_BYTES} bytes")
    return json.loads(raw.decode("utf-8"))


def dpapi_unprotect(blob: bytes) -> bytes | None:
    """Unprotect a CurrentUser DPAPI blob without UI; None when Windows refuses."""
    import ctypes
    from ctypes import wintypes

    class _Blob(ctypes.Structure):
        _fields_ = [
            ("cbData", wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_char)),
        ]

    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    buffer = ctypes.create_string_buffer(blob, len(blob))
    source = _Blob(len(blob), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    result = _Blob()
    ui_forbidden = 0x1
    if not crypt32.CryptUnprotectData(
        ctypes.byref(source), None, None, None, None, ui_forbidden,
        ctypes.byref(result),
    ):
        return None
    try:
        return ctypes.string_at(result.pbData, result.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(result.pbData, ctypes.c_void_p))


def _secret_store_token(path: Path, unprotect: Unprotect) -> tuple[str | None, str]:
    try:
        document = _read_json(path)
    except (OSError, ValueError):
        return None, CURSOR_SECRET_STORE_MISSING_REASON
    if not isinstance(document, dict):
        return None, CURSOR_SECRET_STORE_MISSING_REASON
    if document.get("version") != _STORE_FORMAT_VERSION:
        return None, CURSOR_SECRET_STORE_UNSUPPORTED_REASON
    encoded = document.get("dpapi")
    if not isinstance(encoded, str) or not _BASE64.match(encoded):
        return None, CURSOR_SECRET_STORE_MISSING_REASON
    try:
        plain = unprotect(base64.b64decode(encoded, validate=True))
        credentials = json.loads(plain.decode("utf-8")) if plain else None
    except (OSError, ValueError, binascii.Error):
        credentials = None
    token = credentials.get("accessToken") if isinstance(credentials, dict) else None
    if not isinstance(token, str) or not token.strip():
        return None, CURSOR_SECRET_STORE_MISSING_REASON
    return token, ""


def cursor_windows_access_token(
    environ: Mapping[str, str] | None = None,
    unprotect: Unprotect | None = None,
) -> tuple[str | None, str]:
    """Return ``(token, "")`` or ``(None, reason)`` for the Windows sign-in."""
    environ = os.environ if environ is None else environ
    unprotect = unprotect or dpapi_unprotect
    if environ.get(_CREDENTIAL_LOCKER_ENV) == "1":
        return None, CURSOR_SECRET_STORE_UNSUPPORTED_REASON
    profile = cursor_profile_dir(environ)
    try:
        marker = _read_json(profile / "auth.json")
    except (OSError, ValueError):
        return None, _STALE_REASON
    stored_in = marker.get("storedIn") if isinstance(marker, dict) else None
    if stored_in is None:
        return None, _STALE_REASON
    if stored_in != _DEFAULT_STORE:
        return None, CURSOR_SECRET_STORE_UNSUPPORTED_REASON
    return _secret_store_token(profile / "auth.dpapi", unprotect)


__all__ = [
    "cursor_profile_dir",
    "cursor_windows_access_token",
    "dpapi_unprotect",
]
