"""Connected-env connector types + detection (leaf of the readiness layer).

Holds the value types, tunables, and the read-only detection that classifies
the active ``~/.yoke/config.json`` binding into a connector decision.
Detection touches only files/env -- it never opens a DB connection. The
orchestration (``ensure_ready`` etc.) lives in
:mod:`yoke_core.domain.connected_env_readiness`; the probe + tunnel mechanism
in :mod:`yoke_core.domain.connected_env_readiness_tunnel`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping, Optional

from yoke_core.domain import yoke_connected_env
from yoke_contracts.machine_config.schema import TUNNEL_REQUIRED_KEYS

# Postgres credential env vars (kept in sync with db_backend). An explicit
# operator/test DSN means "do not manage a tunnel" -- the operator pinned the
# target themselves (e.g. the pytest cluster).
PG_DSN_ENV = "YOKE_PG_DSN"
PG_DSN_FILE_ENV = "YOKE_PG_DSN_FILE"

# Connector kinds reported on :class:`ReadinessResult`.
CONNECTOR_LOCAL_SSH_TUNNEL_PG = "local_ssh_tunnel_postgres"
CONNECTOR_REMOTE_POSTGRES = "remote_postgres"  # recognized but unmanaged
CONNECTOR_UNMANAGED = "unmanaged"  # no binding / not postgres / explicit DSN

# Action labels (telemetry-grade, stable strings).
ACTION_NOOP_EXPLICIT_DSN = "noop_explicit_dsn"
ACTION_NOOP_UNMANAGED = "noop_unmanaged"
ACTION_NOOP_UNSUPPORTED = "noop_unsupported"
ACTION_PROBE_OK = "probe_ok"
ACTION_RESTARTED = "restarted"
ACTION_CACHED = "cached"
ACTION_PROBE_FAILED = "probe_failed"

# Tunables (referenced only within the readiness layer; one source each).
CACHE_TTL_SECONDS = 15.0
PROBE_TIMEOUT_SECONDS = 5
PROBE_CONFIRM_ATTEMPTS = 3
PROBE_CONFIRM_DELAY_SECONDS = 0.75
SSH_CONNECT_TIMEOUT_SECONDS = 10
TUNNEL_START_TIMEOUT_SECONDS = 25
TUNNEL_STOP_GRACE_SECONDS = 2.0

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "0.0.0.0"})

# Substrings marking a libpq connect-class failure (tunnel down / refused /
# dropped). Matched case-insensitively against the exception text.
CONNECTION_FAILURE_MARKERS = (
    "connection refused",
    "could not connect",
    "connection to server",
    "could not receive data",
    "could not send data",
    "server closed the connection",
    "no route to host",
    "timeout expired",
    "connection timed out",
    "could not translate host name",
    "network is unreachable",
)

# SSH options proven from the live operator tunnel. BatchMode keeps it
# non-interactive (fail fast, no prompt); ExitOnForwardFailure makes ssh return
# non-zero if the -L forward cannot bind (so a failed restart is detectable);
# the keepalives drop a half-dead forward instead of wedging.
SSH_OPTIONS = (
    ("BatchMode", "yes"),
    ("ExitOnForwardFailure", "yes"),
    ("ServerAliveInterval", "30"),
    ("ServerAliveCountMax", "3"),
    ("StrictHostKeyChecking", "accept-new"),
    ("ConnectTimeout", str(SSH_CONNECT_TIMEOUT_SECONDS)),
)


class ConnectedEnvUnavailable(RuntimeError):
    """Connected env unreachable and self-heal failed.

    Message + attached detail are redacted: connector kind, local bind,
    bastion/remote endpoints, and a redacted probe error -- never the DSN,
    password, secret JSON, or private key.
    """


@dataclass(frozen=True)
class ReadinessResult:
    ok: bool
    environment: Optional[str]
    connector_kind: str
    action: str
    message: str
    redacted_detail: Optional[str] = None


@dataclass(frozen=True)
class TunnelSpec:
    """Resolved SSH local-forward parameters (all non-secret)."""

    local_host: str
    local_port: int
    bastion: str  # ``user@host`` ssh target
    identity_file: str  # path to the key file (not its contents)
    remote_host: str  # Aurora endpoint reached from the bastion
    remote_port: int

    @property
    def forward_spec(self) -> str:
        return f"{self.local_port}:{self.remote_host}:{self.remote_port}"

    @property
    def redacted(self) -> str:
        return (f"local={self.local_host}:{self.local_port} "
                f"bastion={self.bastion} "
                f"remote={self.remote_host}:{self.remote_port}")


@dataclass(frozen=True)
class Detection:
    connector_kind: str
    environment: Optional[str]
    dsn: Optional[str]
    spec: Optional[TunnelSpec]
    local_host: Optional[str] = None
    local_port: Optional[int] = None


def redact(text: str) -> str:
    """Mask DSN/password-shaped tokens in arbitrary error text."""
    if not text:
        return text
    out = []
    for token in text.split():
        low = token.lower()
        if low.startswith(("password=", "pgpassword=")):
            out.append("password=***")
        elif "://" in token and "@" in token:
            scheme, _, rest = token.partition("://")
            out.append(f"{scheme}://***@{rest.rsplit('@', 1)[-1]}")
        else:
            out.append(token)
    return " ".join(out)


def is_loopback(host: Optional[str]) -> bool:
    return bool(host) and host in _LOOPBACK_HOSTS


def explicit_dsn_pinned() -> bool:
    return bool(os.environ.get(PG_DSN_ENV) or os.environ.get(PG_DSN_FILE_ENV))


def dsn_host_port(dsn: str) -> tuple[Optional[str], Optional[int]]:
    host: Optional[str] = None
    port: Optional[int] = None
    for token in dsn.split():
        key, _, value = token.partition("=")
        if key == "host":
            host = value
        elif key == "port":
            try:
                port = int(value)
            except ValueError:
                port = None
    return host, port


def looks_like_connection_failure(exc: BaseException) -> bool:
    """True when *exc* is a psycopg connect-class (tunnel-down) failure."""
    try:
        import psycopg
    except Exception:  # noqa: BLE001
        return False
    if not isinstance(exc, psycopg.OperationalError):
        return False
    text = str(exc).lower()
    return any(marker in text for marker in CONNECTION_FAILURE_MARKERS)


def _tunnel_spec(env: "yoke_connected_env.ConnectedEnv", local_host: str,
                 local_port: int) -> Optional[TunnelSpec]:
    """Build a :class:`TunnelSpec` from the selected env's
    ``connections.<env>.postgres.tunnel`` block, or ``None`` when the block is
    absent/incomplete (so self-heal is not possible)."""
    tunnel = env.connection.get("tunnel")
    if not isinstance(tunnel, Mapping):
        return None
    if any(not tunnel.get(key) for key in TUNNEL_REQUIRED_KEYS):
        return None
    return TunnelSpec(
        local_host=local_host,
        local_port=local_port,
        bastion=str(tunnel["bastion"]),
        identity_file=os.path.expanduser(str(tunnel["identity_file"])),
        remote_host=str(tunnel["remote_host"]),
        remote_port=int(tunnel["remote_port"]),
    )


def detect() -> Detection:
    """Classify the active connected env into a connector decision.

    Reads only files/env -- never opens a DB connection.
    """
    env = yoke_connected_env.load_active()
    if env is None:
        return Detection(CONNECTOR_UNMANAGED, None, None, None)
    if env.backend != "postgres":
        return Detection(CONNECTOR_UNMANAGED, env.environment, None, None)
    conn = env.connection
    host = conn.get("host")
    port = conn.get("port")
    if not is_loopback(host) or not port:
        # Direct/remote Postgres or HTTPS-core (future): recognized, unmanaged.
        return Detection(CONNECTOR_REMOTE_POSTGRES, env.environment, None, None)
    from yoke_core.domain import db_backend

    dsn = db_backend.resolve_pg_dsn()
    spec = _tunnel_spec(env, str(host), int(port))
    return Detection(CONNECTOR_LOCAL_SSH_TUNNEL_PG, env.environment, dsn, spec,
                     local_host=str(host), local_port=int(port))
