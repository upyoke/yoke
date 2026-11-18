"""OS startup facts required even by deliberately restricted child processes."""

import os


# APPDATA and LOCALAPPDATA name the user's profile folders, not authority:
# libraries read them at import (pyfiglet takes os.environ["APPDATA"]), so a
# restricted Windows child without them crashes before doing any work.
WINDOWS_SYSTEM_VARIABLES = (
    "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "PATHEXT", "APPDATA", "LOCALAPPDATA",
)  # fmt: skip


def system_startup_environment() -> dict[str, str]:
    """Preserve Windows Python/networking startup without passing caller authority."""
    return {name: os.environ[name] for name in WINDOWS_SYSTEM_VARIABLES if name in os.environ}
