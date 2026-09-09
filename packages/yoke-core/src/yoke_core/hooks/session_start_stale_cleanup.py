"""Bounded SessionStart stale-session reap for the client-side hook path.

The relayed half already runs the shared janitor on SessionStart
(:mod:`yoke_core.hooks.remote_lifecycle`), so an https-connected machine
sweeps its abandoned actives whenever any session starts. The client-side
dispatch registered and oriented the starting session without ever running
it, so on a machine whose control plane is a local Postgres nothing swept at
all: a claimless session stayed active for hours past its eligibility until
an operator ran the sweep by hand. This is that same guarded janitor, on the
same startup event, for the local half.

Bounded and best-effort by contract, exactly like the Stop / SessionEnd
cleanup beside it: lifecycle work must never break hook transport.
Eligibility, TTLs, holdings, in-flight grounding, and the pre-release
liveness recheck all stay inside ``clean_stale_harness_sessions`` — nothing
here decides who is stale.
"""

from __future__ import annotations

import time
from typing import Optional

from yoke_core.domain.control_plane_transport import local_connection_or_none
from yoke_core.domain.sessions_cleanup import clean_stale_harness_sessions
from yoke_core.hooks.session_end_cleanup import (
    _connect_cleanup_db,
    resolve_cleanup_timeout_ms,
)
from yoke_core.hooks.stdin import emit_session_hook_failed


def run_session_start_stale_cleanup(
    root: str,
    *,
    session_id: str = "",
    executor: Optional[str] = None,
    event_source: str = "SessionStart",
    timeout_override_ms: Optional[int] = None,
    _connect=_connect_cleanup_db,
    _cleanup=clean_stale_harness_sessions,
    _clock=None,
) -> bool:
    """Run the shared janitor once and report whether the sweep executed.

    A control plane this machine cannot open is not a failure: an https
    connection has no local database, and its server-side half already runs
    this janitor for the relayed SessionStart. That returns ``False`` having
    done nothing, and emits no failure telemetry.
    """

    clock = _clock or time.monotonic
    timeout_ms = resolve_cleanup_timeout_ms(override_ms=timeout_override_ms)
    started = clock()
    conn = None
    try:
        from yoke_core.hooks.service_client import target_process_environment

        with target_process_environment(root):
            conn = local_connection_or_none(lambda: _connect(timeout_ms))
            if conn is None:
                return False
            _cleanup(conn)
    except Exception as exc:
        emit_session_hook_failed(
            hook_event=event_source,
            executor=executor or "unknown",
            reason=type(exc).__name__,
            latency_ms=int((clock() - started) * 1000),
            stdin_state="parsed",
            session_id_source="payload",
            session_id=session_id,
            extra={"error": str(exc), "timeout_ms": timeout_ms},
        )
        return False
    finally:
        if conn is not None:
            conn.close()
    return True


__all__ = ["run_session_start_stale_cleanup"]
