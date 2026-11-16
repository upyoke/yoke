"""Finding, terminating, starting, and replacing the local SSH forward.

This module owns the forward as a process: which ssh pids serve this spec,
which process holds the local port, and what it takes to put a working
forward back. :mod:`yoke_core.domain.connected_env_tunnel_coordination` owns
the machine-wide rules about *when* that is allowed, and the Postgres probe
that decides *whether* a forward works lives in
:mod:`yoke_core.domain.connected_env_readiness_tunnel` and is passed in --
so nothing here opens a database connection.

:func:`replace_forward` is the whole policy in one place, and its order
matters. A forward that answers is the working forward whoever started it,
so it is adopted rather than killed; a forward another process has leased is
never terminated; and the port is re-examined after termination, because a
neighbour that binds in that window is a tunnel to adopt, not a bind error
to fail on.
"""

from __future__ import annotations

import os

import psutil
from yoke_contracts.platform_process import (
    handle_from_pid,
    process_command_lines,
    stop_group,
)
import time
from typing import Callable, List, Sequence

from yoke_core.domain.ssh_forward_process import start_forward
from yoke_contracts.designed_wait import announce_designed_wait, poll_every
from yoke_core.domain.connected_env_readiness_connector import (
    ACTION_ADOPTED,
    ACTION_RESTARTED,
    SSH_OPTIONS,
    TUNNEL_START_TIMEOUT_SECONDS,
    TUNNEL_STOP_GRACE_SECONDS,
    ConnectedEnvUnavailable,
    TunnelSpec,
    redact,
)
from yoke_core.domain.connected_env_tunnel_coordination import active_leases

#: How long to keep asking a leased forward whether it answers before giving
#: up on it. A forward carrying a bulk transfer is usually alive and merely
#: slow, so waiting it out is what lets two drivers share the machine; the
#: bound is short because this wait holds the lifecycle lock, and the holder
#: may itself need that lock to heal the forward it is using.
LEASE_WAIT_SECONDS = 30.0
LEASE_WAIT_POLL_SECONDS = 2.0


def _build_ssh_argv(spec: TunnelSpec) -> List[str]:
    """The ``ssh -N -L ...`` argv that (re)establishes the local forward.

    A spec with its own ``ssh_config`` reads that file instead of
    ``~/.ssh/config`` and keeps the host key it pins there: a command-line
    ``StrictHostKeyChecking=accept-new`` would override the file's ``yes``.
    """
    argv = ["ssh"]
    if spec.ssh_config:
        argv += ["-F", spec.ssh_config]
    argv += ["-i", spec.identity_file]
    for key, value in SSH_OPTIONS:
        if spec.ssh_config and key == "StrictHostKeyChecking":
            continue
        argv += ["-o", f"{key}={value}"]
    argv += ["-N", "-L", spec.forward_spec, spec.bastion]
    return argv


def _find_tunnel_pids(spec: TunnelSpec) -> List[int]:
    """PIDs whose SSH argv names exactly this forward and destination."""
    return [
        info.pid
        for info in process_command_lines()
        if _matches_tunnel(info.cmdline, spec)
    ]


def _matches_tunnel(argv: Sequence[str], spec: TunnelSpec) -> bool:
    if not argv or os.path.basename(argv[0]).lower() not in {"ssh", "ssh.exe"}:
        return False
    return (
        any(
            word == "-L"
            and index + 1 < len(argv)
            and argv[index + 1] == spec.forward_spec
            or word == "-L" + spec.forward_spec
            for index, word in enumerate(argv)
        )
        and spec.bastion in argv
    )


def _listening_pids(port: int) -> List[int]:
    """Visible listeners, used to name occupied-port owners on every OS."""
    found = set()
    for process in psutil.process_iter():
        try:
            for entry in process.net_connections(kind="tcp"):
                if entry.status == psutil.CONN_LISTEN and entry.laddr.port == port:
                    found.add(process.pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return sorted(found)


def _process_command(pid: int) -> str:
    return next(
        (" ".join(info.cmdline) for info in process_command_lines() if info.pid == pid),
        "",
    )


def _port_blocker_detail(spec: TunnelSpec) -> str:
    pids = _listening_pids(spec.local_port)
    if not pids:
        return ""
    parts: List[str] = []
    for pid in pids[:5]:
        command = redact(_process_command(pid))
        parts.append(f"pid={pid} command={command or '<unknown>'}")
    return "; ".join(parts)


def _terminate_pids(
    pids: Sequence[int], *, timeout: float = TUNNEL_STOP_GRACE_SECONDS
) -> None:
    wanted = set(pids)
    for info in process_command_lines():
        if info.pid in wanted:
            handle = handle_from_pid(info.pid, info.start_time)
            if handle is not None:
                stop_group(handle, timeout=timeout)


def _start_tunnel(spec: TunnelSpec) -> None:
    """Start OpenSSH in a separate group and await its local listener."""
    try:
        start_forward(
            _build_ssh_argv(spec),
            host=spec.local_host,
            port=spec.local_port,
            timeout=TUNNEL_START_TIMEOUT_SECONDS,
        )
    except RuntimeError as exc:
        raise ConnectedEnvUnavailable(f"{redact(str(exc))} [{spec.redacted}]") from exc


def _healthy_forward_present(spec: TunnelSpec, probe: Callable[[], bool]) -> bool:
    """True when a matching forward holds the port and answers the probe."""
    return bool(_find_tunnel_pids(spec)) and probe()


def _wait_out_leases(spec: TunnelSpec, probe: Callable[[], bool]) -> bool:
    """Re-probe a leased forward for a bounded window; True when it answers.

    Returns as soon as the forward answers (it was slow, not dead) or the last
    lease is released (the holder finished, so replacing it is safe again).
    """
    announce_designed_wait(
        f"another process's lease on the tunnel at local port {spec.local_port}",
        max_wait_seconds=LEASE_WAIT_SECONDS,
        cadence=poll_every(LEASE_WAIT_POLL_SECONDS),
    )
    deadline = time.monotonic() + LEASE_WAIT_SECONDS
    while time.monotonic() < deadline:
        time.sleep(LEASE_WAIT_POLL_SECONDS)
        if probe():
            return True
        if not active_leases(spec.local_port, exclude_pid=os.getpid()):
            return False
    return False


def replace_forward(spec: TunnelSpec, *, probe: Callable[[], bool]) -> str:
    """Put a working forward back, and report which action did it.

    Call only while holding the coordination lifecycle lock for
    ``spec.local_port``. Returns ``ACTION_ADOPTED`` when a forward that was
    already there answers, or ``ACTION_RESTARTED`` when this process started a
    fresh one. Raises :class:`ConnectedEnvUnavailable` when another process's
    lease outlasts the wait below, or a foreign process owns the port.
    """
    if active_leases(spec.local_port, exclude_pid=os.getpid()):
        # Another process is mid-operation through this forward. Terminating
        # it would kill that work, so wait it out: a forward under a bulk
        # transfer usually answers once the load lets up.
        if _wait_out_leases(spec, probe):
            return ACTION_ADOPTED
        holders = active_leases(spec.local_port, exclude_pid=os.getpid())
        if holders:
            raise ConnectedEnvUnavailable(
                "connected-env tunnel is carrying another process's long "
                f"operation and was not replaced [{spec.redacted}]: "
                + "; ".join(holder.line for holder in holders)
                + ". Wait for that operation to finish, or stop it and retry."
            )
    if _healthy_forward_present(spec, probe):
        return ACTION_ADOPTED
    _terminate_pids(_find_tunnel_pids(spec))
    if _healthy_forward_present(spec, probe):
        return ACTION_ADOPTED
    blocker = _port_blocker_detail(spec)
    if blocker:
        raise ConnectedEnvUnavailable(
            "ssh tunnel local port is occupied by a non-matching process "
            f"[{spec.redacted}]: {blocker}"
        )
    _start_tunnel(spec)
    return ACTION_RESTARTED


__all__ = ["replace_forward"]
