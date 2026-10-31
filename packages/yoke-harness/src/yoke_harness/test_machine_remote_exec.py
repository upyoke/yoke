"""Ad hoc remote commands on a registered Test Machine, over the agent's own SSH.

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

import codecs
import locale
import os
from pathlib import Path
import selectors
import subprocess
import sys
import time
from typing import Callable, Mapping, Sequence


KNOWN_HOSTS_DIR_NAME = "test-machine"
KNOWN_HOSTS_FILE_NAME = "known_hosts"
SSH_AUTH_SOCK_ENV = "SSH_AUTH_SOCK"
SSH_CONNECTION_FAILURE_EXIT = 255
DIAGNOSTIC_TAIL_BYTES = 64 * 1024
_READ_CHUNK_BYTES = 8192
SSH_OPTIONS = (
    "IdentityFile=none",
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
    """Where this machine pins every Test Machine host key it has accepted."""
    return yoke_home / KNOWN_HOSTS_DIR_NAME / KNOWN_HOSTS_FILE_NAME


def host_key_options(
    settings: Mapping[str, str], known_hosts: Path | None = None
) -> list[str]:
    """Pin cloud identity to its instance rather than a recyclable address."""
    from yoke_cli.config import machine_config

    known_hosts = known_hosts or known_hosts_path(machine_config.yoke_home())
    create_private_directory(known_hosts.parent)
    alias = settings.get("cloud_instance_id")
    return [
        "-o",
        f"UserKnownHostsFile={known_hosts}",
        "-o",
        *(["-o", f"HostKeyAlias={alias}"] if alias else []),
    ]


def remote_exec_argv(
    *,
    host: str,
    user: str,
    known_hosts: Path,
    command: Sequence[str],
    cloud_instance_id: str | None = None,
) -> list[str]:
    """Build the ssh argv; the command words reach the login shell as ssh sends them."""
    return [
        "ssh",
        "-F",
        "/dev/null",
        *[part for option in SSH_OPTIONS for part in ("-o", option)],
        *host_key_options({"cloud_instance_id": cloud_instance_id}, known_hosts),
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
    popen: Callable[..., subprocess.Popen] = subprocess.Popen,
    administrator_password: str | None = None,
    cloud_instance_id: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Tee output live with inherited stdin; return bounded diagnostic tails.

    Raises :class:`RemoteExecRefusal` before connecting when no ssh-agent is
    reachable, and after ssh itself fails to connect (exit 255), so the
    caller prints one diagnosed reason instead of a bare ssh exit status.
    """
    if not command or any(not word for word in command):
        raise RemoteExecRefusal(
            "test_machine_exec_command_missing",
            "no remote command was given",
            "Pass the command after `--`, e.g. "
            "`yoke test-machine exec --project P --test-machine TEST_MACHINE -- uname -a`.",
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
    from yoke_harness.test_machine_admin import administrator_command

    if administrator_password is not None:
        command = administrator_command(command)
    known_hosts = known_hosts_path(yoke_home)
    create_private_directory(known_hosts.parent)
    argv = remote_exec_argv(
        host=host,
        user=user,
        known_hosts=known_hosts,
        command=command,
        cloud_instance_id=cloud_instance_id,
    )
    try:
        input_options = (
            {"stdin": subprocess.PIPE} if administrator_password is not None else {}
        )
        process = popen(
            argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **input_options
        )
    except OSError as exc:
        raise RemoteExecRefusal(
            "test_machine_ssh_unavailable",
            f"could not start ssh: {exc}",
            "Install OpenSSH's `ssh` client on this machine and put it on PATH.",
        ) from exc
    completed = _stream_command(argv, process=process, password=administrator_password)
    if completed.returncode == SSH_CONNECTION_FAILURE_EXIT:
        raise RemoteExecRefusal(
            "test_machine_ssh_failed",
            f"ssh exited {SSH_CONNECTION_FAILURE_EXIT} reaching {user}@{host}: "
            "ssh's own failure status, unless the "
            f"remote command itself exited {SSH_CONNECTION_FAILURE_EXIT}: "
            + "\n".join((completed.stdout or "", completed.stderr or "")).strip(),
            "Check the host is reachable from this machine and that the "
            "ssh-agent holds a key it authorizes. If the host was rebuilt its "
            "host key changed: remove the pinned entry with "
            f"`ssh-keygen -R {cloud_instance_id or host} -f {known_hosts}` and retry.",
        )
    return completed


def _stream_command(
    argv: list[str],
    *,
    process: subprocess.Popen,
    password: str | None = None,
    redaction_secret: str | None = None,
    stdout=None,
    stderr=None,
    timeout=None,
) -> subprocess.CompletedProcess[str]:
    """Drain both pipes without line buffering or retaining the full output."""
    from yoke_harness.test_machine_admin import PasswordRedactor

    encoding = locale.getpreferredencoding(False)
    secret = (redaction_secret or password or "").encode("utf-8")
    deadline = time.monotonic() + timeout if timeout is not None else None
    with process:
        assert process.stdout is not None and process.stderr is not None
        tails = {process.stdout: bytearray(), process.stderr: bytearray()}
        with selectors.DefaultSelector() as selector:
            try:
                if password is not None:
                    assert process.stdin is not None
                    try:
                        process.stdin.write(secret + b"\n")
                        process.stdin.close()
                    except BrokenPipeError:
                        # SSH may have already refused; drain its diagnosed failure.
                        pass
                for stream, destination in (
                    (process.stdout, stdout if stdout is not None else sys.stdout),
                    (process.stderr, stderr if stderr is not None else sys.stderr),
                ):
                    decoder = codecs.getincrementaldecoder(encoding)(
                        errors="backslashreplace"
                    )
                    selector.register(
                        stream,
                        selectors.EVENT_READ,
                        (destination, decoder, PasswordRedactor(secret)),
                    )
                while selector.get_map():
                    if deadline is not None and time.monotonic() >= deadline:
                        raise subprocess.TimeoutExpired(argv, timeout)
                    for key, _ in selector.select(timeout=1 if deadline else None):
                        stream = key.fileobj
                        chunk = os.read(stream.fileno(), _READ_CHUNK_BYTES)
                        destination, decoder, redactor = key.data
                        safe = redactor.feed(chunk, final=not chunk)
                        destination.write(decoder.decode(safe, final=not chunk))
                        destination.flush()
                        tail = tails[stream]
                        tail.extend(safe)
                        del tail[:-DIAGNOSTIC_TAIL_BYTES]
                        if not chunk:
                            selector.unregister(stream)
                            continue
                returncode = process.wait()
            except BaseException:
                process.kill()
                process.wait()
                raise
        return subprocess.CompletedProcess(
            argv,
            returncode,
            tails[process.stdout].decode(encoding, errors="backslashreplace"),
            tails[process.stderr].decode(encoding, errors="backslashreplace"),
        )


__all__ = [
    "DIAGNOSTIC_TAIL_BYTES",
    "KNOWN_HOSTS_DIR_NAME",
    "KNOWN_HOSTS_FILE_NAME",
    "RemoteExecRefusal",
    "SSH_AUTH_SOCK_ENV",
    "known_hosts_path",
    "remote_exec_argv",
    "run_remote_command",
]
