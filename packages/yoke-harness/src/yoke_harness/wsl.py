"""Read Linux host facts used by WSL setup and machine diagnostics."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def is_wsl() -> bool:
    if not sys.platform.startswith("linux"):
        return False
    if os.environ.get("WSL_DISTRO_NAME"):
        return True
    try:
        return "microsoft" in Path("/proc/sys/kernel/osrelease").read_text().lower()
    except OSError:
        return False


def systemd_running() -> bool:
    """PID 1 is authoritative; a configured boot flag needs a restart."""
    return Path("/proc/1/comm").read_text().strip() == "systemd"
