"""Windows persistent PATH; stdlib only, including during uninstall."""

from __future__ import annotations

import ntpath
from typing import Mapping

USER_PATH_LOCATION = r"HKCU\Environment\Path"


def _read(registry, hive, key: str) -> tuple[str, int]:
    try:
        with registry.OpenKey(hive, key) as handle:
            value, kind = registry.QueryValueEx(handle, "Path")
            return str(value), kind
    except FileNotFoundError:
        return "", registry.REG_EXPAND_SZ


def read_user_path() -> str:
    import winreg

    try:
        return _read(winreg, winreg.HKEY_CURRENT_USER, "Environment")[0]
    except OSError as exc:
        raise OSError(
            f"windows_user_path_unreadable: {exc}; check access to "
            f"{USER_PATH_LOCATION}, then retry yoke path doctor."
        ) from exc


def normalized(entry: str, env: Mapping[str, str]) -> str:
    values = {key.upper(): value for key, value in env.items()}
    import re

    expanded = re.sub(r"%([^%]+)%", lambda m: values.get(m[1].upper(), m[0]), entry)
    return ntpath.normcase(ntpath.normpath(expanded.strip().strip('"')))


def contains(value: str, directory: str, env: Mapping[str, str]) -> bool:
    wanted = normalized(directory, env)
    return any(normalized(entry, env) == wanted for entry in value.split(";") if entry)


def fresh_path(env: Mapping[str, str]) -> str:
    import winreg

    machine, _ = _read(
        winreg,
        winreg.HKEY_LOCAL_MACHINE,
        r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment",
    )
    # Windows builds a new process PATH from machine then user PATH.
    return winreg.ExpandEnvironmentStrings(machine + ";" + read_user_path())


def write_user_path(directory: str, env: Mapping[str, str]) -> list[str]:
    """Repair the uv bin entry; uninstall retains it because uv owns it."""
    import winreg

    try:
        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER,
            "Environment",
            0,
            winreg.KEY_READ | winreg.KEY_WRITE,
        ) as handle:
            value, kind = _read(winreg, winreg.HKEY_CURRENT_USER, "Environment")
            if contains(value, directory, env):
                return []
            winreg.SetValueEx(
                handle, "Path", 0, kind, value + (";" if value else "") + directory
            )
        # Notify Explorer so subsequently opened terminals inherit the repair.
        import ctypes
        from ctypes import wintypes

        result = ctypes.c_size_t()
        broadcast = ctypes.windll.user32.SendMessageTimeoutW
        broadcast.argtypes = [
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPCWSTR,
            wintypes.UINT,
            wintypes.UINT,
            ctypes.POINTER(ctypes.c_size_t),
        ]
        broadcast.restype = wintypes.LPARAM
        if not broadcast(
            0xFFFF,
            0x1A,
            0,
            "Environment",
            0x2,
            5000,
            ctypes.byref(result),
        ):
            raise OSError(
                "Environment notification timed out; sign out and back in to refresh PATH"
            )
        return [USER_PATH_LOCATION]
    except OSError as exc:
        raise OSError(
            f"windows_user_path_write_failed: {exc}; add {directory} to your user "
            "PATH in Windows Environment Variables, open a new terminal, and retry."
        ) from exc
