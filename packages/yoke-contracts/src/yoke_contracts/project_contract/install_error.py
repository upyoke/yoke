"""Shared errors for the installed project contract."""


class ProjectInstallError(RuntimeError):
    """Install/refresh/uninstall cannot proceed; message names the repair."""
