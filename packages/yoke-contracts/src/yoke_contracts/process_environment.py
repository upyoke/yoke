"""OS startup facts required even by deliberately restricted child processes."""

import os


WINDOWS_SYSTEM_VARIABLES = ("SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "PATHEXT")


def system_startup_environment() -> dict[str, str]:
    """Preserve Windows Python/networking startup without passing caller authority."""
    return {name: os.environ[name] for name in WINDOWS_SYSTEM_VARIABLES if name in os.environ}
