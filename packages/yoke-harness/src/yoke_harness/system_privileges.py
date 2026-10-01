"""Select OS authority for an automatic Linux setup command."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys


def command_authority(unavailable_reason: str) -> tuple[list[str], bool]:
    """Return a command prefix and whether the OS password prompt needs a TTY."""
    if os.geteuid() == 0:
        return [], False
    sudo = shutil.which("sudo")
    if sudo:
        try:
            result = subprocess.run(
                [sudo, "-n", "true"], capture_output=True, text=True
            )
        except OSError as exc:
            raise RuntimeError(
                f"{unavailable_reason} OS authority probe failed: {exc}"
            ) from exc
        if result.returncode == 0:
            return [sudo, "-n", "--"], False
        if sys.stdin.isatty() and sys.stderr.isatty():
            return [sudo, "--"], True
    raise RuntimeError(unavailable_reason)
