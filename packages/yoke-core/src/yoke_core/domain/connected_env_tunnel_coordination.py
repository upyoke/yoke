"""Who may replace the shared local SSH forward, and who is using it.

One loopback port carries every process on this machine that talks to the
connected env, so the forward is a shared resource with no owner. Each
process independently deciding to replace it is how two deploy drivers took
each other down: one was six minutes into a bulk copy through the forward
when the other's readiness probe timed out under that load, terminated every
matching ssh pid, and started a fresh one -- the copy died with the forward
it was using, and the retry then lost a bind race against the newcomer
(``bind [127.0.0.1]:PORT: Address already in use``).

Two coordination primitives, both keyed by local port, both machine-wide:

* **The lifecycle lock** serializes probe-and-replace, so no two processes
  are ever inside that decision at once.
* **A use lease** records that some process is mid-operation through the
  forward. :mod:`yoke_core.domain.connected_env_tunnel_lifecycle` refuses to
  replace a leased forward and names the holder instead of terminating its
  work.

State lives under the machine Yoke home rather than a repo, because the
forward is a machine resource: every checkout and worktree shares one.

The failures that shaped this, and why serializing the drivers instead would
not have been enough, are recorded in
``docs/archive/decisions/shared-tunnel-coordination.md``.
"""

from __future__ import annotations

import fcntl
import json
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, List, Optional

from yoke_contracts.machine_config import runtime as machine_config

from yoke_core.domain.connected_env_readiness_connector import (
    CONNECTOR_LOCAL_SSH_TUNNEL_PG,
    ConnectedEnvUnavailable,
    detect,
    redact,
)

COORDINATION_DIR_NAME = "tunnel-coordination"
LIFECYCLE_LOCK_NAME = "lifecycle.lock"
LEASE_DIR_NAME = "leases"
#: How long to wait for another process's probe-and-replace to finish. Sized
#: above one full restart (terminate, start, confirmation probes) so a waiter
#: outlasts a healthy neighbour and only gives up on a wedged one.
LIFECYCLE_LOCK_TIMEOUT_SECONDS = 180.0
LIFECYCLE_LOCK_POLL_SECONDS = 0.25


def coordination_dir(local_port: int) -> Path:
    """Machine-local directory holding this port's lock and leases."""
    return machine_config.yoke_home() / COORDINATION_DIR_NAME / f"port-{local_port}"


# --- lifecycle lock --------------------------------------------------------
@contextmanager
def lifecycle_lock(
    local_port: int, *, timeout: float = LIFECYCLE_LOCK_TIMEOUT_SECONDS,
) -> Iterator[None]:
    """Serialize probe-and-replace of one local forward, machine-wide.

    ``flock`` is released by the kernel when the holder exits, so a killed
    deploy driver cannot wedge the forward for the next one. NOT reentrant:
    a second acquisition in the same process opens a second descriptor and
    would block on itself, so no code holding this may take it again.
    """
    path = coordination_dir(local_port) / LIFECYCLE_LOCK_NAME
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise ConnectedEnvUnavailable(
                        "another process is still replacing the connected-env "
                        f"tunnel on 127.0.0.1:{local_port} after "
                        f"{int(timeout)}s ({_lock_holder(path)}). Wait for it "
                        "to finish, or stop that process and retry."
                    ) from None
                time.sleep(LIFECYCLE_LOCK_POLL_SECONDS)
        _stamp_holder(descriptor)
        yield
    finally:
        os.close(descriptor)  # closing releases the flock


def _stamp_holder(descriptor: int) -> None:
    """Record who holds the lock so a waiter can name it, not just wait."""
    payload = json.dumps({"pid": os.getpid(), "held_since": time.time()})
    try:
        os.lseek(descriptor, 0, os.SEEK_SET)
        os.ftruncate(descriptor, 0)
        os.write(descriptor, payload.encode("utf-8"))
    except OSError:
        return


def _lock_holder(path: Path) -> str:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        pid = int(payload["pid"])
    except (OSError, ValueError, KeyError, TypeError):
        return "holder unknown"
    if not pid_alive(pid):
        return f"last holder pid={pid} is gone"
    return f"holder pid={pid}"


def pid_alive(pid: int) -> bool:
    """True when *pid* still exists (a lease outlives nothing but its holder)."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


# --- use leases ------------------------------------------------------------
@dataclass(frozen=True)
class UseLease:
    """A live claim that some process is mid-operation through the forward."""

    pid: int
    reason: str
    started_at: float

    @property
    def line(self) -> str:
        held = max(0, int(time.time() - self.started_at))
        return f"pid={self.pid} reason={redact(self.reason)} held={held}s"


@contextmanager
def use_lease(local_port: int, reason: str) -> Iterator[Path]:
    """Hold the forward for one long operation; a restart must not kill it.

    The lease is written under the lifecycle lock so it is visible before any
    concurrent replacement can begin terminating pids -- writing it unlocked
    would leave exactly the window this exists to close.
    """
    directory = coordination_dir(local_port) / LEASE_DIR_NAME
    path = directory / f"{os.getpid()}.json"
    payload = {"pid": os.getpid(), "reason": reason, "started_at": time.time()}
    with lifecycle_lock(local_port):
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
    try:
        yield path
    finally:
        path.unlink(missing_ok=True)


@contextmanager
def use_lease_for_active_tunnel(reason: str) -> Iterator[None]:
    """Lease the active managed forward, or do nothing when none is managed.

    Callers running a long transfer (a fleet rehearsal's copy) hold this for
    the whole operation without having to know whether this machine reaches
    the database through a forward at all.
    """
    detection = detect()
    if (
        detection.connector_kind != CONNECTOR_LOCAL_SSH_TUNNEL_PG
        or not detection.local_port
    ):
        yield
        return
    with use_lease(int(detection.local_port), reason):
        yield


def active_leases(
    local_port: int, *, exclude_pid: Optional[int] = None,
) -> List[UseLease]:
    """Live leases on this port; a lease whose holder is gone is removed."""
    directory = coordination_dir(local_port) / LEASE_DIR_NAME
    try:
        entries = sorted(directory.iterdir())
    except OSError:
        return []
    leases: List[UseLease] = []
    for entry in entries:
        lease = _read_lease(entry)
        if lease is None or not pid_alive(lease.pid):
            entry.unlink(missing_ok=True)
            continue
        if exclude_pid is not None and lease.pid == exclude_pid:
            continue
        leases.append(lease)
    return leases


def _read_lease(path: Path) -> Optional[UseLease]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return UseLease(
            pid=int(payload["pid"]),
            reason=str(payload.get("reason", "") or "unnamed operation"),
            started_at=float(payload.get("started_at", 0.0)),
        )
    except (OSError, ValueError, KeyError, TypeError):
        return None


__all__ = [
    "COORDINATION_DIR_NAME",
    "LEASE_DIR_NAME",
    "LIFECYCLE_LOCK_NAME",
    "LIFECYCLE_LOCK_TIMEOUT_SECONDS",
    "UseLease",
    "active_leases",
    "coordination_dir",
    "lifecycle_lock",
    "pid_alive",
    "use_lease",
    "use_lease_for_active_tunnel",
]
