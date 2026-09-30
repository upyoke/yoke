"""Ad hoc remote commands on a registered Test Mac, over the agent's own SSH.

The test-machine capability records the host and login user; this is the
route an agent uses to run a command there outside a QA case. It never reads
``~/.ssh``: a relay-launched session is denied that directory even with its
sandbox off, so ``-F /dev/null`` skips the user's SSH config and host keys
are pinned in a Yoke-managed known_hosts file under the Yoke home. The
identity is whatever the caller's ssh-agent holds; ``IdentityFile=none``
keeps ssh from reaching for default key files there.
"""

from __future__ import annotations

from yoke_contracts.machine_config.directories import create_private_directory

import os
from pathlib import Path
import subprocess
from typing import Callable, Mapping, Sequence


KNOWN_HOSTS_DIR_NAME = "test-machine"
KNOWN_HOSTS_FILE_NAME = "known_hosts"
SSH_AUTH_SOCK_ENV = "SSH_AUTH_SOCK"
SSH_CONNECTION_FAILURE_EXIT = 255
SSH_OPTIONS = (
    "IdentityFile=none",
    "StrictHostKeyChecking=accept-new",
    "BatchMode=yes",
    "ConnectTimeout=10",
)


class RemoteExecRefusal(RuntimeError):
    """A remote command could not start; carries a named code and recovery."""

    def __init__(self, code: str, message: str, recovery: str) -> None:
        super().__init__(message)
        self.code = code
        self.recovery = recovery


def known_hosts_path(yoke_home: Path) -> Path:
    """Where this machine pins every Test Mac host key it has accepted."""
    return yoke_home / KNOWN_HOSTS_DIR_NAME / KNOWN_HOSTS_FILE_NAME


def remote_exec_argv(
    *,
    host: str,
    user: str,
    known_hosts: Path,
    command: Sequence[str],
) -> list[str]:
    """Build the ssh argv; the command words reach the login shell as ssh sends them."""
    return [
        "ssh",
        "-F",
        "/dev/null",
        "-o",
        f"UserKnownHostsFile={known_hosts}",
        *[part for option in SSH_OPTIONS for part in ("-o", option)],
        "--",
        f"{user}@{host}",
        *command,
    ]


def run_remote_command(
    *,
    host: str,
    user: str,
    command: Sequence[str],
    yoke_home: Path,
    environ: Mapping[str, str] = os.environ,
    run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> int:
    """Run one command on the host with inherited stdio; return its exit code.

    Raises :class:`RemoteExecRefusal` before connecting when no ssh-agent is
    reachable, and after ssh itself fails to connect (exit 255), so the
    caller prints one diagnosed reason instead of a bare ssh exit status.
    """
    if not command or any(not word for word in command):
        raise RemoteExecRefusal(
            "test_machine_exec_command_missing",
            "no remote command was given",
            "Pass the command after `--`, e.g. "
            "`yoke test-machine exec --project P --machine M -- uname -a`.",
        )
    if not environ.get(SSH_AUTH_SOCK_ENV):
        raise RemoteExecRefusal(
            "test_machine_ssh_agent_unavailable",
            f"{SSH_AUTH_SOCK_ENV} is not set, so no ssh-agent identity can "
            f"authenticate to {user}@{host}",
            "Start an ssh-agent holding a key the host authorizes "
            "(`ssh-add -l` lists it) and run from a shell that exports "
            f"{SSH_AUTH_SOCK_ENV}.",
        )
    known_hosts = known_hosts_path(yoke_home)
    create_private_directory(known_hosts.parent)
    argv = remote_exec_argv(
        host=host,
        user=user,
        known_hosts=known_hosts,
        command=command,
    )
    try:
        completed = run(argv, check=False)
    except OSError as exc:
        raise RemoteExecRefusal(
            "test_machine_ssh_unavailable",
            f"could not start ssh: {exc}",
            "Install OpenSSH's `ssh` client on this machine and put it on PATH.",
        ) from exc
    if completed.returncode == SSH_CONNECTION_FAILURE_EXIT:
        raise RemoteExecRefusal(
            "test_machine_ssh_failed",
            f"ssh exited {SSH_CONNECTION_FAILURE_EXIT} reaching {user}@{host}: "
            "ssh's own failure status (its message is above), unless the "
            f"remote command itself exited {SSH_CONNECTION_FAILURE_EXIT}",
            "Check the host is reachable from this machine and that the "
            "ssh-agent holds a key it authorizes. If the host was rebuilt its "
            "host key changed: remove the pinned entry with "
            f"`ssh-keygen -R {host} -f {known_hosts}` and retry.",
        )
    return int(completed.returncode)


__all__ = [
    "KNOWN_HOSTS_DIR_NAME",
    "KNOWN_HOSTS_FILE_NAME",
    "RemoteExecRefusal",
    "SSH_AUTH_SOCK_ENV",
    "known_hosts_path",
    "remote_exec_argv",
    "run_remote_command",
]
