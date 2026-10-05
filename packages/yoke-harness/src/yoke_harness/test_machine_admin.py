"""Stored administrator credentials and private sudo command input."""

from __future__ import annotations

import shlex
from collections.abc import Sequence

from yoke_cli.config.capability_secrets import (
    MachineCapabilitySecretError,
    read_machine_capability_secret,
)
from yoke_contracts.machine_config.desktop_access import DESKTOP_PASSWORD_KEY
from yoke_contracts.machine_config.test_machine import test_machine_capability_type


MAX_PASSWORD_BYTES = 4096


def administrator_password(*, project: str, machine: str, os_name: str) -> str:
    """Read only in product code; never include the value in a refusal."""
    from yoke_harness.test_machine_remote_exec import RemoteExecRefusal

    if os_name not in {"macos", "linux"}:
        raise RemoteExecRefusal(
            "test_machine_admin_os_unsupported",
            "--admin requires a macOS or Linux test machine",
            "Select a registered macOS or Linux machine with --machine NAME.",
        )
    cap_type = test_machine_capability_type(machine)
    recovery = (
        "Import the machine administrator password from a private file with "
        f"`yoke projects capability secret set --project {project} "
        f"--cap-type {cap_type} --key {DESKTOP_PASSWORD_KEY} --value-file FILE`."
    )
    try:
        password = read_machine_capability_secret(
            project, cap_type, DESKTOP_PASSWORD_KEY
        )
    except MachineCapabilitySecretError:
        raise RemoteExecRefusal(
            "test_machine_admin_credential_unreadable",
            f"{cap_type}.{DESKTOP_PASSWORD_KEY} is unreadable or empty",
            recovery,
        ) from None
    if password is None:
        raise RemoteExecRefusal(
            "test_machine_admin_credential_missing",
            f"{cap_type}.{DESKTOP_PASSWORD_KEY} is missing",
            recovery,
        )
    if (
        any(char in password for char in "\r\n\0")
        or len(password.encode()) > MAX_PASSWORD_BYTES
    ):
        raise RemoteExecRefusal(
            "test_machine_admin_credential_invalid",
            f"{cap_type}.{DESKTOP_PASSWORD_KEY} must be one bounded password line",
            recovery,
        )
    return password


def administrator_command(command: Sequence[str]) -> list[str]:
    """Keep the existing remote-shell semantics and isolate the command's stdin.

    The root shell disconnects stdin before executing command text, so even
    a NOPASSWD sudo rule cannot forward unused credential input to the command.
    -k requires fresh authentication rather than borrowing cached authority.
    """
    script = "exec </dev/null; " + " ".join(command)
    return ["sudo -k -S -p '' -- /bin/sh -c " + shlex.quote(script)]


class PasswordRedactor:
    """Redact a password even when SSH splits it between output reads."""

    def __init__(self, password: bytes = b"") -> None:
        self.password = password
        self.pending = b""

    def feed(self, chunk: bytes, *, final: bool = False) -> bytes:
        if not self.password:
            return chunk
        value = self.pending + chunk
        parts = []
        while (index := value.find(self.password)) >= 0:
            parts.extend((value[:index], b"[REDACTED]"))
            value = value[index + len(self.password) :]
        retained = 0
        if not final:
            for length in range(min(len(value), len(self.password) - 1), 0, -1):
                if value.endswith(self.password[:length]):
                    retained = length
                    break
        split = len(value) - retained
        parts.append(value[:split])
        self.pending = value[split:]
        return b"".join(parts)
