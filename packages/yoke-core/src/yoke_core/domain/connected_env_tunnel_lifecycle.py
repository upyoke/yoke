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
import subprocess
import time
from typing import Callable, List, Sequence

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
    """The ``ssh -N -f -L ...`` argv that (re)establishes the local forward."""
    argv = ["ssh", "-i", spec.identity_file]
    for key, value in SSH_OPTIONS:
        argv += ["-o", f"{key}={value}"]
    argv += ["-N", "-f", "-L", spec.forward_spec, spec.bastion]
    return argv


def _find_tunnel_pids(spec: TunnelSpec) -> List[int]:
    """PIDs of existing ssh forwards matching this spec.

    The match pattern starts with ``-L``; the ``--`` prevents BSD/macOS
    ``pgrep`` from reading it as an option. Return code 1 means no matches, but
    return code 2+ is a search failure and must surface before we try to start
    a colliding tunnel.
    """
    pattern = f"-L {spec.forward_spec}"
    try:
        result = subprocess.run(
            ["pgrep", "-f", "--", pattern],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode >= 2:
        detail = redact((result.stderr or result.stdout or "").strip())
        raise ConnectedEnvUnavailable(
            f"could not enumerate tunnel pids (pgrep rc={result.returncode}) "
            f"[{spec.redacted}]: {detail}"
        )
    pids = _parse_pids(result.stdout)
    for pid in _listening_pids(spec.local_port):
        if pid not in pids and _pid_matches_tunnel(pid, spec):
            pids.append(pid)
    return pids


def _parse_pids(text: str) -> List[int]:
    pids: List[int] = []
    for line in text.split():
        try:
            pids.append(int(line))
        except ValueError:
            continue
    return pids


def _listening_pids(port: int) -> List[int]:
    """PIDs listening on *port* (best-effort, used for occupied-port clarity)."""
    try:
        result = subprocess.run(
            ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    return _parse_pids(result.stdout)


def _process_command(pid: int) -> str:
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip()


def _pid_matches_tunnel(pid: int, spec: TunnelSpec) -> bool:
    command = _process_command(pid)
    if not command:
        return False
    return (
        "ssh" in command
        and spec.forward_spec in command
        and spec.bastion in command
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


def _terminate_pids(pids: Sequence[int]) -> None:
    for pid in pids:
        try:
            os.kill(pid, 15)  # SIGTERM
        except (ProcessLookupError, PermissionError, OSError):
            continue
    if pids:
        time.sleep(TUNNEL_STOP_GRACE_SECONDS)
    for pid in pids:
        try:
            os.kill(pid, 9)  # SIGKILL any survivor
        except (ProcessLookupError, PermissionError, OSError):
            continue


def _start_tunnel(spec: TunnelSpec) -> None:
    """Spawn the backgrounded ssh forward; raise on a non-zero start."""
    argv = _build_ssh_argv(spec)
    try:
        result = subprocess.run(
            argv, capture_output=True, text=True,
            timeout=TUNNEL_START_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise ConnectedEnvUnavailable(
            f"ssh tunnel start timed out after {TUNNEL_START_TIMEOUT_SECONDS}s "
            f"[{spec.redacted}]"
        ) from exc
    except (OSError, subprocess.SubprocessError) as exc:
        raise ConnectedEnvUnavailable(
            f"ssh tunnel start could not run [{spec.redacted}]: "
            f"{redact(str(exc))}"
        ) from exc
    if result.returncode != 0:
        detail = redact((result.stderr or result.stdout or "").strip())
        raise ConnectedEnvUnavailable(
            f"ssh tunnel start failed (rc={result.returncode}) "
            f"[{spec.redacted}]: {detail}"
        )


def _healthy_forward_present(spec: TunnelSpec, probe: Callable[[], bool]) -> bool:
    """True when a matching forward holds the port and answers the probe."""
    return bool(_find_tunnel_pids(spec)) and probe()


def _wait_out_leases(spec: TunnelSpec, probe: Callable[[], bool]) -> bool:
    """Re-probe a leased forward for a bounded window; True when it answers.

    Returns as soon as the forward answers (it was slow, not dead) or the last
    lease is released (the holder finished, so replacing it is safe again).
    """
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
