"""Windows desktop inventory from installed registry metadata, never app execution.

MSIX apps are read from the per-user AppModel package repository, whose subkey
names are package full names (``Name_Version_Arch_ResourceId_PublisherId``).
Win32 installs are read from the HKCU then HKLM ``Uninstall`` keys. Nothing here
starts the app or spawns PowerShell, so the relay poll stays fast.
"""

from __future__ import annotations

from dataclasses import dataclass
import sys
from typing import Protocol

MSIX_REPOSITORY_KEY = (
    r"Software\Classes\Local Settings\Software\Microsoft\Windows"
    r"\CurrentVersion\AppModel\Repository\Packages"
)
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"


@dataclass(frozen=True)
class WindowsDesktopIdentity:
    """What identifies one desktop surface on Windows.

    ``msix_family`` is ``Name_PublisherId`` as ``Get-AppxPackage`` reports
    ``PackageFamilyName``; ``uninstall_display_names`` are exact
    ``DisplayName`` values of a Win32 ``Uninstall`` entry.
    """

    label: str
    msix_family: str | None = None
    uninstall_display_names: tuple[str, ...] = ()

    def describe(self) -> str:
        sought = []
        if self.msix_family:
            sought.append(f"MSIX package family {self.msix_family}")
        if self.uninstall_display_names:
            names = " or ".join(repr(name) for name in self.uninstall_display_names)
            sought.append(f"HKCU/HKLM Uninstall DisplayName {names}")
        return " or ".join(sought)


# Identities recorded on windows-native-lab-2 (YOK-5632): Claude and Codex
# install as MSIX packages; Cursor's per-user Inno installer registers
# "Cursor (User)", and its machine-wide installer registers "Cursor".
WINDOWS_DESKTOP_IDENTITIES = {
    "claude-desktop": WindowsDesktopIdentity(
        "Claude Desktop", msix_family="Claude_pzs8sxrjxfjjc"
    ),
    "codex-desktop": WindowsDesktopIdentity(
        "Codex desktop", msix_family="OpenAI.Codex_2p2nqsd0c76g0"
    ),
    "cursor-desktop": WindowsDesktopIdentity(
        "Cursor desktop", uninstall_display_names=("Cursor (User)", "Cursor")
    ),
}


class RegistryReader(Protocol):
    def subkeys(self, hive: str, path: str) -> tuple[str, ...]:
        """Return subkey names, or ``()`` when the key does not exist."""

    def value(self, hive: str, path: str, name: str) -> object | None:
        """Return a value, or ``None`` when the key or value does not exist."""


class WinregReader:
    """Read-only registry access through the stdlib ``winreg`` module."""

    def __init__(self) -> None:
        import winreg

        self._winreg = winreg

    def _open(self, hive: str, path: str):
        winreg = self._winreg
        root = {"HKCU": winreg.HKEY_CURRENT_USER, "HKLM": winreg.HKEY_LOCAL_MACHINE}
        access = winreg.KEY_READ | (winreg.KEY_WOW64_64KEY if hive == "HKLM" else 0)
        return winreg.OpenKey(root[hive], path, 0, access)

    def subkeys(self, hive: str, path: str) -> tuple[str, ...]:
        try:
            key = self._open(hive, path)
        except FileNotFoundError:
            return ()
        with key:
            count = self._winreg.QueryInfoKey(key)[0]
            return tuple(self._winreg.EnumKey(key, index) for index in range(count))

    def value(self, hive: str, path: str, name: str) -> object | None:
        try:
            key = self._open(hive, path)
        except FileNotFoundError:
            return None
        with key:
            try:
                return self._winreg.QueryValueEx(key, name)[0]
            except FileNotFoundError:
                return None


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split(".") if part.isdigit())


def _msix_version(reader: RegistryReader, family: str) -> str | None:
    versions = []
    for full_name in reader.subkeys("HKCU", MSIX_REPOSITORY_KEY):
        parts = full_name.split("_")
        if len(parts) == 5 and f"{parts[0]}_{parts[4]}" == family:
            versions.append(parts[1])
    return max(versions, key=_version_key) if versions else None


def _uninstall_version(reader: RegistryReader, names: tuple[str, ...]) -> str | None:
    for hive in ("HKCU", "HKLM"):
        for entry in reader.subkeys(hive, UNINSTALL_KEY):
            path = f"{UNINSTALL_KEY}\\{entry}"
            if reader.value(hive, path, "DisplayName") not in names:
                continue
            version = reader.value(hive, path, "DisplayVersion")
            if not isinstance(version, str) or not version.strip():
                raise ValueError(
                    f"{hive}\\{path} has no readable DisplayVersion; reinstall the app"
                )
            return version.strip()
    return None


def read_windows_desktop_version(
    surface: str,
    *,
    reader: RegistryReader | None = None,
) -> tuple[str, str]:
    """Return ``(source, version)`` or raise ``FileNotFoundError`` when absent."""
    identity = WINDOWS_DESKTOP_IDENTITIES[surface]
    if reader is None:
        if sys.platform != "win32":
            raise RuntimeError("the Windows registry is only readable on Windows")
        reader = WinregReader()
    if identity.msix_family:
        version = _msix_version(reader, identity.msix_family)
        if version:
            return "msix", version
    if identity.uninstall_display_names:
        version = _uninstall_version(reader, identity.uninstall_display_names)
        if version:
            return "registry", version
    raise FileNotFoundError(
        f"desktop_app_missing: no {identity.describe()} is installed for this user; "
        f"install {identity.label} as this user and retry"
    )


__all__ = [
    "MSIX_REPOSITORY_KEY",
    "UNINSTALL_KEY",
    "WINDOWS_DESKTOP_IDENTITIES",
    "RegistryReader",
    "WindowsDesktopIdentity",
    "WinregReader",
    "read_windows_desktop_version",
]
