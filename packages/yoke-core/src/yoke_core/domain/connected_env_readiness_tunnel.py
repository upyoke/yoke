"""Probe + coordinated restart for the connected-env readiness layer.

A real Postgres probe (psycopg ``SELECT 1``) is authoritative -- a listening
local port is necessary but not sufficient. The probe uses psycopg DIRECTLY
(never ``db_backend.connect``) so the readiness layer cannot recurse into the
caller it wraps. ``evaluate`` is the detect -> probe -> (replace) -> re-probe
core; the cache + public API live in
:mod:`yoke_core.domain.connected_env_readiness`, the forward's processes in
:mod:`yoke_core.domain.connected_env_tunnel_lifecycle`, and the machine-wide
rules about who may replace it in
:mod:`yoke_core.domain.connected_env_tunnel_coordination`.

The forward is shared, so the decision to replace it is taken under the
machine-wide lifecycle lock and re-checked there: by the time a waiter is
admitted, the neighbour it was queued behind has usually already healed the
forward, and the right answer is to use it rather than replace it again.
"""

from __future__ import annotations

import socket
import time
from typing import Optional

from yoke_core.domain.connected_env_readiness_connector import (
    ACTION_ADOPTED,
    ACTION_NOOP_UNMANAGED,
    ACTION_NOOP_UNSUPPORTED,
    ACTION_PROBE_FAILED,
    ACTION_PROBE_OK,
    CONNECTOR_REMOTE_POSTGRES,
    CONNECTOR_UNMANAGED,
    PROBE_CONFIRM_ATTEMPTS,
    PROBE_CONFIRM_DELAY_SECONDS,
    PROBE_TIMEOUT_SECONDS,
    TUNNEL_REQUIRED_KEYS,
    ConnectedEnvUnavailable,
    Detection,
    ReadinessResult,
    TunnelSpec,
    detect,
    dsn_host_port,
    redact,
)
from yoke_core.domain import connected_env_tunnel_coordination as _coordination
from yoke_core.domain import connected_env_tunnel_lifecycle as _lifecycle


# --- probes ----------------------------------------------------------------
def _port_is_listening(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _probe_postgres(dsn: str, *, timeout: int = PROBE_TIMEOUT_SECONDS) -> None:
    """Open a real psycopg connection and run ``SELECT 1``; raise on failure.

    ``connect_timeout`` is sized for a forward under bulk load, not for an
    idle one: a saturated forward answers slowly, and calling that dead is
    what once terminated a healthy tunnel mid-copy. A forward that is really
    gone still fails fast, on the cheap port check above.
    """
    import psycopg

    with psycopg.connect(dsn, autocommit=True, connect_timeout=timeout) as conn:
        conn.execute("SELECT 1")


# SQLSTATE classes proving the server ANSWERED through the forward: the
# credential or database selection was refused, but reachability — the only
# thing this layer manages — is intact. Declaring these "down" would block
# connection acquisition, where managed-secret rotation recovery (AWSPREVIOUS)
# and precise auth errors live.
_SERVER_ANSWERED_SQLSTATES = frozenset({
    "28000",  # invalid_authorization_specification
    "28P01",  # invalid_password
    "3D000",  # invalid_catalog_name
})
# Connect-phase psycopg errors do not always carry a sqlstate; the relayed
# server FATAL text is then the only classification signal. These are the
# libpq-relayed message bodies for the same three SQLSTATE classes.
_SERVER_ANSWERED_SIGNATURES = (
    "password authentication failed",
    "no pg_hba.conf entry",
    "does not exist",
)


def server_answered(exc: Exception) -> bool:
    sqlstate = str(getattr(exc, "sqlstate", "") or "")
    if sqlstate:
        return sqlstate in _SERVER_ANSWERED_SQLSTATES
    message = str(exc)
    return "FATAL" in message and any(
        signature in message for signature in _SERVER_ANSWERED_SIGNATURES
    )


def _probe_failure(dsn: str) -> Optional[str]:
    """Probe once; return ``None`` on success or a redacted failure cause.

    Cheap port check first (a closed local port is a definitely-down
    forward), then the authoritative psycopg probe. The cause names the
    exception class so an auth/TLS/database refusal is distinguishable from
    a dead forward — historically both collapsed into one "unreachable"
    verdict and the operator had to guess which side was broken. A
    server-answered refusal (bad password, missing database) counts as
    reachable: the forward works, and the credential story belongs to the
    connect layer's rotation recovery, not to tunnel management.
    """
    try:
        host, port = dsn_host_port(dsn)
        if host and port and not _port_is_listening(host, port):
            return f"local forward {host}:{port} is not listening"
        _probe_postgres(dsn)
        return None
    except Exception as exc:  # noqa: BLE001 -- classify, then report as down
        if server_answered(exc):
            return None
        first_line = str(exc).strip().splitlines()[0] if str(exc).strip() else ""
        return redact(f"{type(exc).__name__}: {first_line}"[:300])


def _probe_retry(dsn: str, *, attempts: int = PROBE_CONFIRM_ATTEMPTS,
                 delay: float = PROBE_CONFIRM_DELAY_SECONDS) -> Optional[str]:
    """Return ``None`` if any probe succeeds across a short confirmation
    window, else the last redacted failure cause.

    The window is the load tolerance: one slow answer under a bulk transfer
    is not a verdict, so a forward is only called dead after every attempt
    across that span has failed.
    """
    failure: Optional[str] = None
    for i in range(max(1, attempts)):
        failure = _probe_failure(dsn)
        if failure is None:
            return None
        if i + 1 < attempts:
            time.sleep(delay)
    return failure


# --- core evaluation -------------------------------------------------------
def _ok(detection: Detection, action: str, message: str,
        detail: Optional[str] = None) -> ReadinessResult:
    return ReadinessResult(
        ok=True, environment=detection.environment,
        connector_kind=detection.connector_kind, action=action,
        message=message, redacted_detail=detail,
    )


def _replace_forward(spec: TunnelSpec, dsn: str) -> str:
    """Coordinate one replacement of the shared forward, and name the action."""
    return _lifecycle.replace_forward(
        spec, probe=lambda: _probe_failure(dsn) is None,
    )


def evaluate(*, allow_restart: bool) -> ReadinessResult:
    """Detect + probe, replacing the tunnel when ``allow_restart`` is set.

    Returns an ``ok`` result on success/noop. Raises
    :class:`ConnectedEnvUnavailable` only when ``allow_restart`` is set and the
    managed tunnel could not be restored. With ``allow_restart`` false (status
    reporting) a failed probe yields ``ok=False`` instead of raising, and no
    lock is taken: reporting never contends with a live replacement.
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
    first_failure = _probe_failure(dsn)
    if first_failure is None:
        return _ok(detection, ACTION_PROBE_OK,
                   "connected-env Postgres reachable", detail)

    if not allow_restart:
        return ReadinessResult(
            ok=False, environment=detection.environment,
            connector_kind=detection.connector_kind, action=ACTION_PROBE_FAILED,
            message="connected-env Postgres unreachable (probe failed)",
            redacted_detail=f"{detail} cause={first_failure}",
        )

    if detection.spec is None:
        raise ConnectedEnvUnavailable(
            "connected-env Postgres is unreachable and no usable "
            f"connections.{detection.environment}.postgres.tunnel block is "
            "declared to self-heal. Restart the SSH forward manually or add "
            f"a complete tunnel block (keys: {', '.join(TUNNEL_REQUIRED_KEYS)})"
            f". {detail} cause={first_failure}"
        )

    spec = detection.spec
    with _coordination.lifecycle_lock(spec.local_port):
        # Re-probe inside the lock: a neighbour we queued behind may already
        # have healed the forward, and replacing a working one is the bug.
        if _probe_retry(dsn) is None:
            return _ok(detection, ACTION_PROBE_OK,
                       "connected-env Postgres reachable (recovered before "
                       "restart)", detail)
        action = _replace_forward(spec, dsn)

    restart_failure = _probe_retry(dsn)
    if restart_failure is None:
        message = (
            "connected-env tunnel already restored by another process; adopted"
            if action == ACTION_ADOPTED
            else "connected-env tunnel restarted and Postgres reachable"
        )
        return _ok(detection, action, message,
                   f"{detail} tunnel={spec.redacted}")

    raise ConnectedEnvUnavailable(
        f"connected-env tunnel was {action} but Postgres is still unreachable. "
        f"{detail} tunnel={spec.redacted} cause={restart_failure}"
    )
