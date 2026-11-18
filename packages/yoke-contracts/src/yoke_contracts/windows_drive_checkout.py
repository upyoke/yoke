"""Warn when a Linux project checkout sits on a WSL Windows drive mount.

WSL mounts each Windows drive at ``/mnt/<letter>``. Linux file operations and
permissions behave poorly there, so doctor and the setup wizard both warn with
this one message. It is a warning, never a refusal: existing code on a Windows
drive can still be adopted.
"""

from __future__ import annotations

import re
import sys

_WINDOWS_DRIVE_MOUNT = re.compile(r"^/mnt/[a-zA-Z](?:/|$)")


def is_windows_drive_path(path: str) -> bool:
    """True when ``path`` is a ``/mnt/<drive letter>`` mount or lies under one."""
    return bool(_WINDOWS_DRIVE_MOUNT.match(path))


def windows_drive_checkout_warning(path: str) -> str | None:
    """The warning for a checkout on a Windows drive on Linux, else ``None``."""
    if not sys.platform.startswith("linux") or not is_windows_drive_path(path):
        return None
    return (
        f"{path} is on a Windows drive. Move the checkout into the Linux "
        "filesystem, for example ~/projects, and bind that checkout to Yoke."
    )


__all__ = ["is_windows_drive_path", "windows_drive_checkout_warning"]
