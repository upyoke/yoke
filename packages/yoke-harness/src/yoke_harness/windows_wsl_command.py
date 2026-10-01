"""Carry a Linux shell command through Windows OpenSSH without shell expansion."""

from __future__ import annotations

import base64


def windows_wsl_input(command: str, input_text: str | None) -> tuple[str, str]:
    """Stream the command before its original stdin, avoiding Windows argv limits.

    Bash consumes only the first base64 line. The sourced command still sees
    the remaining stdin, including the JSON used by Linux golden operations.
    """
    reader = (
        "IFS= read -r payload; source /dev/fd/3 3< <(printf %s $payload | base64 -d)"
    )
    payload = base64.b64encode(command.encode("utf-8")).decode("ascii")
    return reader, payload + "\n" + (input_text or "")


def windows_wsl_command(command: str) -> str:
    """Run in the SSH user's default WSL2 distro and preserve its exit status.

    Windows OpenSSH can enter cmd.exe or PowerShell. An encoded PowerShell
    invocation avoids both shells interpreting quotes, percent signs or
    metacharacters in the Linux command. The WSL distro's configured default
    user owns the Linux home; it must be a non-root user. Start there rather
    than inheriting the Windows SSH account's directory under /mnt/c.
    """
    # Windows PowerShell's legacy native argv handling strips embedded quote
    # bytes even from a PowerShell literal. Decode in Bash instead. A separate
    # descriptor leaves stdin available for the existing text-upload protocol.
    payload = base64.b64encode(command.encode("utf-8")).decode("ascii")
    literal = f"'source /dev/fd/3 3< <(printf %s {payload} | base64 -d)'"
    script = f"& wsl.exe --cd '~' -e /bin/bash -lc {literal}; exit $LASTEXITCODE"
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    return (
        "powershell.exe -NoLogo -NoProfile -NonInteractive -EncodedCommand " + encoded
    )
