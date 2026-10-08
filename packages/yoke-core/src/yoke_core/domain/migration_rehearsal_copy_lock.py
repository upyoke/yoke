"""Machine-wide admission for one physical rehearsal cluster/database pair.

The stable file's flock is authority. Metadata only explains contention. Copy
subprocesses inherit the open description: parent death cannot admit another
driver while a surviving transfer still uses the copy. Never unlock explicitly
or unlink the lock file; close each user's descriptor after its work stops.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import subprocess
import time
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Iterator

from yoke_contracts.machine_config import runtime as machine_config
from yoke_contracts.machine_config.directories import create_private_directory
from yoke_core.domain.postgres_cluster import ClusterSpec, SOCKET_PORT

_DESCRIPTORS: ContextVar[tuple[int, ...]] = ContextVar(
    "rehearsal_copy_descriptors", default=()
)


class RehearsalCopyBusy(RuntimeError):
    """The physical copy is still in use by another driver or its child."""


def child_descriptors() -> tuple[int, ...]:
    """Descriptors every copy-using subprocess must retain until it exits."""
    return _DESCRIPTORS.get()


def run_child(argv, *, timeout: float, **kwargs) -> subprocess.CompletedProcess:
    """Retain copy admission, and reap interrupted children before cleanup."""
    with subprocess.Popen(
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        pass_fds=child_descriptors(),
        **kwargs,
    ) as process:
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except BaseException:
            if process.poll() is None:
                process.kill()
            process.communicate()
            raise
        return subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)


def actual_database_name(name: str) -> str:
    """Match PostgreSQL's UTF-8 identifier clipping for creation and access."""
    return name.encode("utf-8")[:63].decode("utf-8", errors="ignore")


def lock_path(spec: ClusterSpec, copy_name: str) -> Path:
    # The socket endpoint, not checkout, source environment, credentials or
    # declared root, determines which physical local cluster receives the copy.
    # PostgreSQL clips identifiers at a UTF-8 character boundary at 63 bytes.
    actual_name = actual_database_name(copy_name)
    endpoint = spec.sock_dir.resolve()
    try:
        info = endpoint.stat()
        cluster = [info.st_dev, info.st_ino]
    except FileNotFoundError:
        cluster = str(endpoint)  # absent endpoint can only produce a failed copy
    identity = json.dumps([cluster, SOCKET_PORT, actual_name])
    key = hashlib.sha256(identity.encode()).hexdigest()
    return machine_config.yoke_home() / "rehearsal-copy-coordination" / f"{key}.lock"


def _holder(descriptor: int) -> str:
    try:
        metadata = json.loads(os.pread(descriptor, 4096, 0))
        pid = int(metadata["pid"])
        elapsed = max(0, int(time.time() - float(metadata["started_at"])))
        return (
            f"driver pid={pid}, held={elapsed}s (a surviving child may hold admission)"
        )
    except (OSError, ValueError, KeyError, TypeError, OverflowError):
        return (
            "holder diagnostics unavailable (driver or surviving child holds admission)"
        )


@contextmanager
def copy_lock(spec: ClusterSpec, copy_name: str) -> Iterator[None]:
    """Refuse immediately when busy; hold through all operations and cleanup."""
    path = lock_path(spec, copy_name)
    create_private_directory(path.parent)
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RehearsalCopyBusy(
                f"rehearsal_copy_busy: {_holder(descriptor)}; "
                "keep the holder running and retry preflight after it finishes"
            ) from None
        # Diagnostics cannot decide admission or make an acquired lock fail.
        try:
            metadata = json.dumps({"pid": os.getpid(), "started_at": time.time()})
            os.ftruncate(descriptor, 0)
            os.pwrite(descriptor, metadata.encode(), 0)
        except OSError:
            pass
        token = _DESCRIPTORS.set((*child_descriptors(), descriptor))
        try:
            yield
        finally:
            _DESCRIPTORS.reset(token)
    finally:
        os.close(descriptor)
