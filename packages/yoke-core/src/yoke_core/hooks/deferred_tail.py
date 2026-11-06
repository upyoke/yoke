"""Post-response hook bookkeeping with bounded database lock waits."""

from __future__ import annotations

from contextvars import copy_context
from typing import Any, Callable


def bounded_tail_connection():
    """Bound only background transactions; request registration stays inline."""
    from yoke_core.domain.db_backend import connection_is_postgres
    from yoke_core.domain.db_helpers import connect

    conn = connect()
    try:
        if connection_is_postgres(conn):
            conn.execute("SET LOCAL lock_timeout = '2000ms'")
    except Exception:
        conn.close()
        raise
    return conn


def deferred_flush(
    telem_records: list,
    dispatch_extra: dict[str, Any],
    *,
    observed_session,
    event_name: str,
    context,
    final_outcome: str,
    timed_out: bool,
    failed: bool,
) -> Callable[[int], None]:
    """Keep observation, posture and lifecycle order after the response."""

    def flush(server_wall_ms: int) -> None:
        from yoke_core.hooks import telemetry
        from yoke_core.hooks.remote_lifecycle import run_remote_session_lifecycle
        from yoke_core.hooks.session_turn_posture_tail import (
            persist_accepted_hook_turn_posture,
        )

        dispatch_extra["server_wall_ms"] = server_wall_ms
        telemetry.flush_hook_telemetry(
            telem_records,
            observed_session=observed_session,
            connection_factory=bounded_tail_connection,
        )
        persist_accepted_hook_turn_posture(
            event_name=event_name,
            session_id=context.session_id or "",
            observed_at=getattr(context, "now", None),
            final_outcome=final_outcome,
            timed_out=timed_out,
            failed=failed,
            connection_factory=bounded_tail_connection,
        )
        if context.session_id and final_outcome != "deny":
            run_remote_session_lifecycle(
                event_name,
                context,
                connection_factory=bounded_tail_connection,
            )

    scope = copy_context()
    return lambda server_wall_ms: scope.run(flush, server_wall_ms)
