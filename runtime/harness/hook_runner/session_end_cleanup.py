"""Bounded Stop / SessionEnd cleanup helper.

The hook path should stay simple: run the existing ``end_session_if_empty``
domain primitive now and preserve claims plus chain checkpoints.
"""

from __future__ import annotations

import time
from typing import Optional

from yoke_core.domain.db_helpers import connect
from yoke_core.domain.runtime_settings import get_int
from yoke_core.domain.sessions import end_session_if_empty as domain_end_session_if_empty
from runtime.harness.hook_runner.stdin import emit_session_hook_failed


CLEANUP_TIMEOUT_CONFIG_KEY = "hook_session_end_cleanup_timeout_ms"
CLEANUP_TIMEOUT_DEFAULT_MS = 2500


def resolve_cleanup_timeout_ms(*, override_ms: Optional[int] = None) -> int:
    """Resolve the Stop / SessionEnd cleanup DB busy timeout."""

    if override_ms is not None and override_ms > 0:
        return int(override_ms)
    value = get_int(CLEANUP_TIMEOUT_CONFIG_KEY, CLEANUP_TIMEOUT_DEFAULT_MS)
    return value if value > 0 else CLEANUP_TIMEOUT_DEFAULT_MS


def _connect_cleanup_db(timeout_ms: int):
    return connect(busy_timeout_ms=timeout_ms)


def _failure(
    *,
    session_id: str,
    executor: Optional[str],
    event_source: str,
    reason: str,
    latency_ms: int,
    extra: Optional[dict] = None,
) -> bool:
    emit_session_hook_failed(
        hook_event=event_source,
        executor=executor or "unknown",
        reason=reason,
        latency_ms=latency_ms,
        stdin_state="parsed",
        session_id_source="payload",
        session_id=session_id,
        extra=extra,
    )
    return False


def run_session_end_cleanup_in_process(
    session_id: str,
    *,
    executor: Optional[str] = None,
    event_source: str = "unknown",
    timeout_override_ms: Optional[int] = None,
    _connect=_connect_cleanup_db,
    _cleanup=domain_end_session_if_empty,
    _clock=None,
) -> bool:
    """Server-side ``end_session_if_empty`` for relayed Stop / SessionEnd.

    Remote evaluation skips ``session_dispatch`` (delegated to the relay
    client), and on no-checkout machines the client-side evaluation
    no-ops (not a Yoke target) — without this server half no such
    relayed session could ever end. The cleanup itself is a pure DB
    operation: run it on the canonical connection with the same
    claims/chain guards and failure telemetry as the client path, minus
    the client-checkout environment pinning. Checkout machines may run
    both halves; the guarded cleanup is idempotent (an already-ended
    session no-ops).
    """

    clock = _clock or time.monotonic
    timeout_ms = resolve_cleanup_timeout_ms(override_ms=timeout_override_ms)
    started = clock()
    conn = None
    try:
        conn = _connect(timeout_ms)
        _cleanup(conn, session_id)
    except Exception as exc:
        return _failure(
            session_id=session_id, executor=executor, event_source=event_source,
            reason=type(exc).__name__,
            latency_ms=int((clock() - started) * 1000),
            extra={"error": str(exc), "timeout_ms": timeout_ms},
        )
    finally:
        if conn is not None:
            conn.close()
    return True


def run_session_end_cleanup(
    root: str,
    session_id: str,
    *,
    executor: Optional[str] = None,
    event_source: str = "unknown",
    timeout_override_ms: Optional[int] = None,
    _connect=_connect_cleanup_db,
    _cleanup=domain_end_session_if_empty,
    _clock=None,
) -> bool:
    """Run ``end_session_if_empty`` once and return whether it completed cleanly."""

    clock = _clock or time.monotonic
    timeout_ms = resolve_cleanup_timeout_ms(override_ms=timeout_override_ms)
    started = clock()
    conn = None
    try:
        from runtime.harness.hook_runner.service_client import (
            target_process_environment,
        )

        with target_process_environment(root):
            conn = _connect(timeout_ms)
            _cleanup(conn, session_id)
    except Exception as exc:
        return _failure(
            session_id=session_id, executor=executor, event_source=event_source,
            reason=type(exc).__name__,
            latency_ms=int((clock() - started) * 1000),
            extra={"error": str(exc), "timeout_ms": timeout_ms},
        )
    finally:
        if conn is not None:
            conn.close()
    return True


__all__ = [
    "CLEANUP_TIMEOUT_CONFIG_KEY",
    "CLEANUP_TIMEOUT_DEFAULT_MS",
    "_connect_cleanup_db",
    "resolve_cleanup_timeout_ms",
    "run_session_end_cleanup",
    "run_session_end_cleanup_in_process",
]
