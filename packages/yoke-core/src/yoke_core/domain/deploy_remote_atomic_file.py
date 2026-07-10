"""Atomic remote-file convergence over the deployment SSH seam."""

from __future__ import annotations

import re
import shlex
from typing import TYPE_CHECKING

from yoke_core.domain.deploy_environment_settings import DeployEnvironment

if TYPE_CHECKING:
    from yoke_core.domain.deploy_remote import CommandResult, CommandRunner


_REMOTE_FILE_CONVERGENCE_PROGRAM = """
import fcntl
import os
from pathlib import Path
import stat
import sys
import tempfile

operation = sys.argv[1]
target = Path(sys.argv[2])
if operation not in {"remove", "write"}:
    raise ValueError("remote file operation must be remove or write")
mode = int(sys.argv[3], 8) if operation == "write" else None
temporary_prefix = f".{target.name}."
temporary_suffix = ".tmp"
lock_name = f".{target.name}.lock"
directory_descriptor = os.open(
    target.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
)
lock_descriptor = -1
descriptor = -1
temporary_name = ""
try:
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise OSError("remote platform cannot safely open the file lock")
    for _attempt in range(3):
        try:
            lock_descriptor = os.open(
                lock_name,
                os.O_RDWR | os.O_CREAT | os.O_EXCL
                | getattr(os, "O_CLOEXEC", 0) | nofollow,
                0o600,
                dir_fd=directory_descriptor,
            )
            break
        except FileExistsError:
            try:
                lock_descriptor = os.open(
                    lock_name,
                    os.O_RDWR | getattr(os, "O_CLOEXEC", 0) | nofollow,
                    dir_fd=directory_descriptor,
                )
                break
            except FileNotFoundError:
                continue
    else:
        raise FileNotFoundError("remote file lock changed during open")
    lock_stat = os.fstat(lock_descriptor)
    if (
        not stat.S_ISREG(lock_stat.st_mode)
        or lock_stat.st_uid != os.geteuid()
        or lock_stat.st_nlink != 1
        or stat.S_IMODE(lock_stat.st_mode) & 0o077
    ):
        raise PermissionError("remote file lock is not owner-only")
    fcntl.flock(lock_descriptor, fcntl.LOCK_EX)

    removed_temporary = False
    with os.scandir(target.parent) as entries:
        for entry in entries:
            if not (
                entry.name.startswith(temporary_prefix)
                and entry.name.endswith(temporary_suffix)
            ):
                continue
            try:
                entry_stat = entry.stat(follow_symlinks=False)
            except FileNotFoundError:
                continue
            if (
                stat.S_ISREG(entry_stat.st_mode)
                and entry_stat.st_uid == os.geteuid()
            ):
                try:
                    os.unlink(entry.path)
                    removed_temporary = True
                except FileNotFoundError:
                    pass
    if removed_temporary:
        os.fsync(directory_descriptor)

    if operation == "remove":
        try:
            os.unlink(target)
        except FileNotFoundError:
            pass
    else:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=temporary_prefix, suffix=temporary_suffix, dir=target.parent,
        )
        os.fchmod(descriptor, mode)
        stream = os.fdopen(descriptor, "wb")
        descriptor = -1
        with stream:
            stream.write(sys.stdin.buffer.read())
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, target)
        temporary_name = ""
    os.fsync(directory_descriptor)
finally:
    if descriptor >= 0:
        os.close(descriptor)
    if temporary_name:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
    if lock_descriptor >= 0:
        os.close(lock_descriptor)
    os.close(directory_descriptor)
""".strip()


def push_remote_file(
    runner: CommandRunner,
    env: DeployEnvironment,
    *,
    content: str,
    remote_path: str,
    mode: str,
    sudo: bool = True,
    timeout: int = 120,
) -> CommandResult:
    """Write *content* atomically through SSH stdin, never through argv."""
    if re.fullmatch(r"[0-7]{3,4}", str(mode)) is None:
        raise ValueError("remote file mode must be a three- or four-digit octal value")
    prefix = "sudo " if sudo else ""
    remote = " ".join(
        (
            f"{prefix}python3",
            "-c",
            shlex.quote(_REMOTE_FILE_CONVERGENCE_PROGRAM),
            "write",
            _remote_path_argument(remote_path),
            shlex.quote(str(mode)),
        )
    )
    from yoke_core.domain.deploy_remote import run_remote

    return run_remote(runner, env, remote, input_text=content, timeout=timeout)


def remove_remote_file(
    runner: CommandRunner,
    env: DeployEnvironment,
    *,
    remote_path: str,
    sudo: bool = True,
    timeout: int = 120,
) -> CommandResult:
    """Remove a target and same-owner temporary files under its lock."""
    prefix = "sudo " if sudo else ""
    remote = " ".join(
        (
            f"{prefix}python3",
            "-c",
            shlex.quote(_REMOTE_FILE_CONVERGENCE_PROGRAM),
            "remove",
            _remote_path_argument(remote_path),
        )
    )
    from yoke_core.domain.deploy_remote import run_remote

    return run_remote(runner, env, remote, timeout=timeout)


def _remote_path_argument(remote_path: str) -> str:
    path_text = str(remote_path)
    if path_text.startswith("~/"):
        # Quoting the whole path would suppress remote tilde expansion. Expand
        # only HOME and independently shell-quote the caller-provided suffix.
        return '"$HOME"/' + shlex.quote(path_text[2:])
    return shlex.quote(path_text)


__all__ = ["push_remote_file", "remove_remote_file"]
