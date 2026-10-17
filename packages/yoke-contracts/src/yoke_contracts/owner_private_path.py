"""Cross-platform owner-private local path validation."""

from __future__ import annotations

import os
from pathlib import Path
import stat

from yoke_contracts import windows_private_directory


_WINDOWS_PERMISSIONS = os.name == "nt"


def is_owner_private_file(path: str | Path) -> bool:
    """Return whether a regular file is accessible only to trusted principals."""
    selected = Path(path)
    try:
        info = selected.stat(follow_symlinks=False)
    except OSError:
        return False
    if not stat.S_ISREG(info.st_mode):
        return False
    if _WINDOWS_PERMISSIONS:
        return windows_private_directory.is_private_file(selected)
    if hasattr(os, "getuid") and info.st_uid != os.getuid():
        return False
    return not bool(stat.S_IMODE(info.st_mode) & 0o077)


__all__ = ["is_owner_private_file"]
