"""Make an owner-private path readable by other users, on POSIX and Windows."""

from __future__ import annotations

import os
from pathlib import Path
import stat
import subprocess

# Builtin Users: every interactive account on a Windows machine.
_WINDOWS_USERS_SID = "*S-1-5-32-545"


def share_with_other_users(path: Path) -> None:
    """Grant other users read access, so owner-only checks must refuse it.

    POSIX adds group and other read bits; Windows has no mode bits that
    carry access, so it grants Builtin Users read access in the DACL.
    """
    if os.name == "nt":
        subprocess.run(
            ["icacls", str(path), "/grant", f"{_WINDOWS_USERS_SID}:(R)"],
            check=True,
            capture_output=True,
        )
        return
    path.chmod(stat.S_IMODE(path.stat().st_mode) | 0o044)
