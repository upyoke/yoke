"""Probe + SSH-tunnel restart mechanism for the connected-env readiness layer.

A real Postgres probe (psycopg ``SELECT 1``) is authoritative -- a listening
local port is necessary but not sufficient. The probe uses psycopg DIRECTLY
(never ``db_backend.connect``) so the readiness layer cannot recurse into the
caller it wraps. ``evaluate`` is the detect -> probe -> (restart) -> re-probe
core; the cache + public API live in
:mod:`yoke_core.domain.connected_env_readiness`.
"""

from __future__ import annotations

import os
import socket
import subprocess
import time
from typing import Optional, Sequence

from yoke_core.domain.connected_env_readiness_connector import (
    ACTION_NOOP_UNMANAGED,
    ACTION_NOOP_UNSUPPORTED,
    ACTION_PROBE_FAILED,
    ACTION_PROBE_OK,
    ACTION_RESTARTED,
    CONNECTOR_REMOTE_POSTGRES,
    CONNECTOR_UNMANAGED,
    PROBE_CONFIRM_ATTEMPTS,
    PROBE_CONFIRM_DELAY_SECONDS,
    PROBE_TIMEOUT_SECONDS,
    SSH_OPTIONS,
    TUNNEL_REQUIRED_KEYS,
    TUNNEL_START_TIMEOUT_SECONDS,
    TUNNEL_STOP_GRACE_SECONDS,
    ConnectedEnvUnavailable,
    Detection,
    ReadinessResult,
    TunnelSpec,
    detect,
    dsn_host_port,
    redact,
)


# --- probes ----------------------------------------------------------------
def _port_is_listening(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _probe_postgres(dsn: str, *, timeout: int = PROBE_TIMEOUT_SECONDS) -> None:
    """Open a real psycopg connection and run ``SELECT 1``; raise on failure.

    Short ``connect_timeout`` so a listening-but-dead forward fails fast
    instead of wedging.
    """
    import psycopg

    with psycopg.connect(dsn, autocommit=True, connect_timeout=timeout) as conn:
        conn.execute("SELECT 1")


def _probe(dsn: str) -> bool:
    """Boolean probe: cheap port check first (a closed local port is a
    definitely-down forward), then the authoritative psycopg probe."""
    try:
        host, port = dsn_host_port(dsn)
        if host and port and not _port_is_listening(host, port):
            return False
        _probe_postgres(dsn)
        return True
    except Exception:  # noqa: BLE001 -- any connect-class failure means "down"
        return False


def _probe_retry(dsn: str, *, attempts: int = PROBE_CONFIRM_ATTEMPTS,
                 delay: float = PROBE_CONFIRM_DELAY_SECONDS) -> bool:
    """Return true if any probe succeeds across a short confirmation window."""
    for i in range(max(1, attempts)):
        if _probe(dsn):
            return True
        if i + 1 < attempts:
            time.sleep(delay)
    return False


# --- ssh tunnel restart ----------------------------------------------------
def _build_ssh_argv(spec: TunnelSpec) -> list[str]:
    """The ``ssh -N -f -L ...`` argv that (re)establishes the local forward."""
    argv = ["ssh", "-i", spec.identity_file]
    for key, value in SSH_OPTIONS:
        argv += ["-o", f"{key}={value}"]
    argv += ["-N", "-f", "-L", spec.forward_spec, spec.bastion]
    return argv


def _find_tunnel_pids(spec: TunnelSpec) -> list[int]:
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


def _parse_pids(text: str) -> list[int]:
    pids: list[int] = []
    for line in text.split():
        try:
            pids.append(int(line))
        except ValueError:
            continue
    return pids


def _listening_pids(port: int) -> list[int]:
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
    parts: list[str] = []
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


def _restart_tunnel(spec: TunnelSpec) -> None:
    """Kill any stale forward holding the local port, then start a fresh one."""
    _terminate_pids(_find_tunnel_pids(spec))
    blocker = _port_blocker_detail(spec)
    if blocker:
        raise ConnectedEnvUnavailable(
            "ssh tunnel local port is occupied by a non-matching process "
            f"[{spec.redacted}]: {blocker}"
        )
    _start_tunnel(spec)


# --- core evaluation -------------------------------------------------------
def _ok(detection: Detection, action: str, message: str,
        detail: Optional[str] = None) -> ReadinessResult:
    return ReadinessResult(
        ok=True, environment=detection.environment,
        connector_kind=detection.connector_kind, action=action,
        message=message, redacted_detail=detail,
    )


def evaluate(*, allow_restart: bool) -> ReadinessResult:
    """Detect + probe, restarting the tunnel when ``allow_restart`` is set.

    Returns an ``ok`` result on success/noop. Raises
    :class:`ConnectedEnvUnavailable` only when ``allow_restart`` is set and the
    managed tunnel could not be restored. With ``allow_restart`` false (status
    reporting) a failed probe yields ``ok=False`` instead of raising.
    """
    detection = detect()
    if detection.connector_kind == CONNECTOR_UNMANAGED:
        return _ok(detection, ACTION_NOOP_UNMANAGED,
                   "no managed connected-env tunnel; nothing to do")
    if detection.connector_kind == CONNECTOR_REMOTE_POSTGRES:
        return _ok(detection, ACTION_NOOP_UNSUPPORTED,
                   "connected env is direct/remote Postgres; tunnel readiness "
                   "is not managed for this connector")

    # Managed local SSH tunnel.
    dsn = detection.dsn or ""
    detail = (f"connector={detection.connector_kind} "
              f"env={detection.environment} "
              f"local={detection.local_host}:{detection.local_port}")
    if _probe(dsn):
        return _ok(detection, ACTION_PROBE_OK,
                   "connected-env Postgres reachable", detail)

    if not allow_restart:
        return ReadinessResult(
            ok=False, environment=detection.environment,
            connector_kind=detection.connector_kind, action=ACTION_PROBE_FAILED,
            message="connected-env Postgres unreachable (probe failed)",
            redacted_detail=detail,
        )

    if detection.spec is None:
        raise ConnectedEnvUnavailable(
            "connected-env Postgres is unreachable and no usable "
            f"connections.{detection.environment}.postgres.tunnel block is "
            "declared to self-heal. Restart the SSH forward manually or add "
            f"a complete tunnel block (keys: {', '.join(TUNNEL_REQUIRED_KEYS)})"
            f". {detail}"
        )

    if _probe_retry(dsn):
        return _ok(detection, ACTION_PROBE_OK,
                   "connected-env Postgres reachable (recovered before restart)",
                   detail)

    _restart_tunnel(detection.spec)
    if _probe_retry(dsn):
        return _ok(detection, ACTION_RESTARTED,
                   "connected-env tunnel restarted and Postgres reachable",
                   f"{detail} restarted_tunnel={detection.spec.redacted}")

    raise ConnectedEnvUnavailable(
        "connected-env tunnel was restarted but Postgres is still unreachable. "
        f"{detail} tunnel={detection.spec.redacted}"
    )
