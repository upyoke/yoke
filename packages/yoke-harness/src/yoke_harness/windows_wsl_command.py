"""Carry a Linux shell command through Windows OpenSSH without shell expansion."""

from __future__ import annotations

import base64


def windows_wsl_command(command: str) -> str:
    """Run in the SSH user's default WSL2 distro and preserve its exit status.

    Windows OpenSSH can enter cmd.exe or PowerShell. An encoded PowerShell
    invocation avoids both shells interpreting quotes, percent signs or
    metacharacters in the Linux command. The WSL distro's configured default
    user owns the Linux home; it must be a non-root user.
    """
    literal = "'" + command.replace("'", "''") + "'"
    script = f"& wsl.exe -e /bin/bash -lc {literal}; exit $LASTEXITCODE"
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    return (
        "powershell.exe -NoLogo -NoProfile -NonInteractive -EncodedCommand " + encoded
    )
