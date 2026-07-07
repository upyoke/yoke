"""Connected-environment readiness for the local Yoke runtime.

Yoke's active control plane is a cloud Postgres (Aurora). On an operator
machine the runtime reaches it through a local SSH port-forward declared on
the selected env-keyed connection in ``~/.yoke/config.json``
(``connections.<env>.postgres`` with a loopback ``host`` + ``port`` and a
``tunnel`` block). Selection follows the normal env precedence (``--env`` /
``YOKE_ENV`` / ``active_env``), so an override like ``YOKE_ENV=<env>-db-admin``
under an https default is covered. When the operator changes WiFi the forward
dies and every Yoke command starts failing with ``connection to server at
"127.0.0.1" ... failed: Connection refused``.

This module is the single readiness abstraction that fixes that bridge without
teaching every caller about SSH. It is a *connector* abstraction, not a
Mac-specific tunnel product: today the only connector is
``local_ssh_tunnel_postgres``; the future cloud-runtime connector (local CLI -> remote
Yoke core over HTTPS, remote core owns Aurora) slots in beside it.

Contract:

- :func:`ensure_ready` is checked at *connection acquisition*, not per SQL
  statement, and a short in-process cache means a recently-confirmed-healthy
  tunnel is not re-probed on every connection.
- On an actual connection failure the cache is bypassed and a forced re-probe
  (and, if needed, a tunnel restart) runs.
- It MUST NOT call :func:`yoke_core.domain.db_backend.connect` (that is the
  caller that wraps *this*): the probe uses psycopg directly to avoid recursion.
- If self-heal fails it raises :class:`ConnectedEnvUnavailable` loudly, with
  redacted detail only -- never the DSN, password, secret JSON, or key.

Mechanism + detection live in the sibling ``_connector`` / ``_tunnel`` modules;
this module owns the cache, the public API, and the operator-debug CLI (NOT the
future ``yoke env`` lifecycle)::

    python3 -m yoke_core.domain.connected_env_readiness status
    python3 -m yoke_core.domain.connected_env_readiness activate
"""

from __future__ import annotations

import sys
import threading
import time
from typing import Callable, Optional, Sequence, TypeVar

from yoke_core.domain.connected_env_readiness_connector import (
    ACTION_CACHED,
    ACTION_NOOP_EXPLICIT_DSN,
    ACTION_PROBE_FAILED,
    CACHE_TTL_SECONDS,
    CONNECTOR_LOCAL_SSH_TUNNEL_PG,
    CONNECTOR_REMOTE_POSTGRES,
    CONNECTOR_UNMANAGED,
    PG_DSN_ENV,
    PG_DSN_FILE_ENV,
    CONNECTION_FAILURE_MARKERS,
    ConnectedEnvUnavailable,
    ReadinessResult,
    TunnelSpec,
    detect,
    explicit_dsn_pinned,
    looks_like_connection_failure,
    redact,
)
from yoke_core.domain import connected_env_readiness_tunnel as _tunnel
from yoke_core.domain import yoke_connected_env

T = TypeVar("T")

# --- in-process readiness cache -------------------------------------------
_LOCK = threading.RLock()
_CACHE: Optional[ReadinessResult] = None
_CACHE_AT: float = 0.0
# Seam for tests: defaults to the real monotonic clock.
_now: Callable[[], float] = time.monotonic


def reset_cache() -> None:
    """Clear the in-process readiness cache (tests / forced re-evaluation)."""
    global _CACHE, _CACHE_AT
    with _LOCK:
        _CACHE = None
        _CACHE_AT = 0.0


def _cached_result() -> Optional[ReadinessResult]:
    if _CACHE is None or (_now() - _CACHE_AT) > CACHE_TTL_SECONDS:
        return None
    return ReadinessResult(
        ok=_CACHE.ok, environment=_CACHE.environment,
        connector_kind=_CACHE.connector_kind, action=ACTION_CACHED,
        message=_CACHE.message, redacted_detail=_CACHE.redacted_detail,
    )


def _store_cache(result: ReadinessResult) -> None:
    global _CACHE, _CACHE_AT
    if result.ok:
        _CACHE = result
        _CACHE_AT = _now()


def _noop_explicit_dsn() -> ReadinessResult:
    message = f"{PG_DSN_ENV}/{PG_DSN_FILE_ENV} pinned; tunnel not managed"
    try:
        from yoke_core.domain.cloud_db_secret_dsn import env_binding_selected

        if env_binding_selected():
            message = "managed database secret environment pinned; tunnel not managed"
    except Exception:  # noqa: BLE001 - readiness fallback stays best-effort
        pass
    return ReadinessResult(
        ok=True, environment=None, connector_kind=CONNECTOR_UNMANAGED,
        action=ACTION_NOOP_EXPLICIT_DSN,
        message=message,
    )


# --- public API ------------------------------------------------------------
def ensure_ready(*, force: bool = False) -> ReadinessResult:
    """Ensure the connected-env Postgres authority is reachable.

    Cheap on the happy path: an explicit operator/test DSN short-circuits to a
    noop, and a warm cache returns without probing. On a cold cache (or
    ``force``) it probes real Postgres and, for the managed local-SSH-tunnel
    connector, restarts the forward and re-probes once. Raises
    :class:`ConnectedEnvUnavailable` (loud, redacted) when a managed tunnel
    cannot be restored.
    """
    # Explicit operator/test DSN: never manage a tunnel. Checked first and
    # uncached so a test toggling the env var sees it immediately and the hot
    # test path never contends on the lock.
    from yoke_core.domain.cloud_db_secret_dsn import env_binding_selected

    if explicit_dsn_pinned() or env_binding_selected():
        return _noop_explicit_dsn()
    with _LOCK:
        if not force:
            cached = _cached_result()
            if cached is not None:
                return cached
        result = _tunnel.evaluate(allow_restart=True)
        _store_cache(result)
        return result


def status() -> ReadinessResult:
    """Report current readiness WITHOUT restarting (operator-debug / CLI).

    Never raises and never restarts the tunnel; ``ok`` reflects the live probe.
    """
    from yoke_core.domain.cloud_db_secret_dsn import env_binding_selected

    if explicit_dsn_pinned() or env_binding_selected():
        return _noop_explicit_dsn()
    try:
        return _tunnel.evaluate(allow_restart=False)
    except yoke_connected_env.ConnectedEnvError as exc:
        return ReadinessResult(
            ok=False, environment=None, connector_kind=CONNECTOR_UNMANAGED,
            action=ACTION_PROBE_FAILED,
            message=f"connected-env binding is unusable: {exc}",
        )


def is_local_tunnel_connection_error(exc: BaseException) -> bool:
    """True when *exc* is a connect-class failure of the managed local tunnel.

    Used by ``db_backend`` to decide whether a failed connect should trigger
    self-heal. False when an explicit DSN is pinned (operator/test override) or
    the active connector is not the managed local SSH tunnel, so non-tunnel
    failures propagate unchanged.
    """
    if isinstance(exc, ConnectedEnvUnavailable):
        return False  # already a heal failure; do not loop
    from yoke_core.domain.cloud_db_secret_dsn import env_binding_selected

    if explicit_dsn_pinned() or env_binding_selected():
        return False
    if not looks_like_connection_failure(exc):
        return False
    try:
        return detect().connector_kind == CONNECTOR_LOCAL_SSH_TUNNEL_PG
    except Exception:  # noqa: BLE001 -- detection hiccup: do not claim ownership
        return False


def is_connection_unavailable_error(exc: BaseException) -> bool:
    """True when *exc* means the DB authority / connected env is unreachable.

    Broader than :func:`is_local_tunnel_connection_error` (which gates
    self-heal on the managed connector + no explicit DSN): this ignores the
    connector and the explicit-DSN override. Fail-loud callers such as the
    board rebuild use it so a DB-down render never reports success, whatever
    the active connector.
    """
    if isinstance(exc, ConnectedEnvUnavailable):
        return True
    if isinstance(exc, yoke_connected_env.ConnectedEnvError):
        return True
    return looks_like_connection_failure(exc)


def connect_with_readiness(opener: Callable[[], T]) -> T:
    """Open a DB connection via *opener* with acquisition-time readiness.

    1. Proactively ensure readiness (cache-gated, cheap on a warm cache; a noop
       when no tunnel is managed).
    2. Call *opener*.
    3. If the open fails with a managed-local-tunnel connect error, force a
       re-probe + tunnel restart and retry *opener* exactly once. A second
       failure is wrapped in a loud, redacted :class:`ConnectedEnvUnavailable`.

    Readiness is therefore checked at connection acquisition, not per
    statement; the cache keeps that check off the hot path.
    """
    try:
        ensure_ready(force=False)
    except ConnectedEnvUnavailable:
        raise  # tunnel down and unhealable -- fail loud, do not mask
    except Exception:  # noqa: BLE001 -- detection hiccup: let opener be authoritative
        pass

    try:
        return opener()
    except Exception as exc:  # noqa: BLE001
        if not is_local_tunnel_connection_error(exc):
            raise
        ensure_ready(force=True)  # raises ConnectedEnvUnavailable if heal fails
        try:
            return opener()
        except Exception as exc2:  # noqa: BLE001
            raise ConnectedEnvUnavailable(
                "connected-env Postgres is still unreachable after tunnel "
                f"self-heal: {redact(str(exc2))}"
            ) from exc2


def registration_failure_remediation(error_text: str) -> Optional[str]:
    """A connected-env remediation line for a session-registration failure.

    Returns ``None`` when the failure does not look like connected-env
    unavailability, so callers only surface the hint when relevant.
    """
    if not error_text:
        return None
    low = error_text.lower()
    if not any(marker in low for marker in CONNECTION_FAILURE_MARKERS):
        return None
    return (
        "Connected-env/tunnel may be down (Postgres authority unreachable). "
        "Recover: python3 -m yoke_core.domain.connected_env_readiness activate"
    )


# --- operator-debug CLI ----------------------------------------------------
def _print_result(result: ReadinessResult) -> None:
    flag = "ok" if result.ok else "UNAVAILABLE"
    print(f"[{flag}] connector={result.connector_kind} "
          f"environment={result.environment} action={result.action}")
    print(f"  {result.message}")
    if result.redacted_detail:
        print(f"  {result.redacted_detail}")


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    command = args[0] if args else "status"
    if command in {"-h", "--help"}:
        print(__doc__)
        return 0
    if command not in {"status", "activate"}:
        print(f"unknown command: {command!r} (expected 'status' or 'activate')",
              file=sys.stderr)
        return 2
    try:
        result = ensure_ready(force=True) if command == "activate" else status()
    except ConnectedEnvUnavailable as exc:
        print(f"[UNAVAILABLE] {redact(str(exc))}", file=sys.stderr)
        return 1
    _print_result(result)
    return 0 if result.ok else 1


__all__ = [
    "ConnectedEnvUnavailable",
    "ReadinessResult",
    "TunnelSpec",
    "CONNECTOR_LOCAL_SSH_TUNNEL_PG",
    "CONNECTOR_REMOTE_POSTGRES",
    "CONNECTOR_UNMANAGED",
    "ensure_ready",
    "status",
    "connect_with_readiness",
    "is_local_tunnel_connection_error",
    "is_connection_unavailable_error",
    "registration_failure_remediation",
    "redact",
    "reset_cache",
    "main",
]


if __name__ == "__main__":  # pragma: no cover -- exercised via subprocess
    sys.exit(main())
