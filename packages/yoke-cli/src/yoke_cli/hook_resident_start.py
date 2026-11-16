"""Own startup lock custody and detached evaluator launch."""

import os
import subprocess
import sys
from pathlib import Path

from yoke_cli.hook_resident_paths import ResidentPaths
from yoke_contracts import platform_file_lock
from yoke_contracts.hook_resident_transport import uses_named_pipe


def _open_start_lock(path: Path) -> int | None:
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        platform_file_lock.acquire_exclusive_nonblocking(descriptor)
    except BlockingIOError:
        os.close(descriptor)
        return None
    os.set_inheritable(descriptor, True)
    return descriptor


def _start_resident(
    paths: ResidentPaths, environment: dict[str, str]
) -> subprocess.Popen | None:
    """Launch a resident unless another caller holds the start lock."""
    lock_fd = _open_start_lock(paths.lock)
    if lock_fd is None:
        return None
    log_fd = -1
    try:
        from yoke_contracts import platform_process

        log_fd = os.open(paths.log, os.O_CREAT | os.O_WRONLY | os.O_APPEND, 0o600)
        return platform_process.spawn_group(
            [
                sys.executable,
                "-m",
                "yoke_harness.hook_resident",
                "--socket",
                str(paths.socket),
                "--lock-path" if uses_named_pipe() else "--lock-fd",
                str(paths.lock) if uses_named_pipe() else str(lock_fd),
            ],
            stdin=subprocess.DEVNULL,
            stdout=log_fd,
            stderr=log_fd,
            cwd=str(paths.state_dir),
            env=environment,
            close_fds=True,
            **({} if uses_named_pipe() else {"pass_fds": (lock_fd,)}),
        ).process
    except OSError as exc:
        from yoke_cli.hook_resident_client import ResidentUnavailable

        raise ResidentUnavailable(
            "YOKE_HOOK_RESIDENT_UNREACHABLE",
            f"resident start failed ({type(exc).__name__})",
            log_path=paths.log,
        ) from None
    finally:
        if log_fd >= 0:
            os.close(log_fd)
        os.close(lock_fd)
