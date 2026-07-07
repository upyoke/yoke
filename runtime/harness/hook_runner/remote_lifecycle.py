"""Server-side session lifecycle for relayed hook events.

``session_dispatch`` is delegated to the relay client, but on no-checkout
machines the client-side evaluation no-ops (not a Yoke target) — when
this server half didn't exist, no such relayed session could ever end and
the active set grew monotonically. Stop / SessionEnd
run the bounded claims/chain-guarded end cleanup here; SessionStart runs
the stale-session reap so abandoned actives get swept somewhere. Checkout
machines may run both halves — the guarded cleanup and the reap are
idempotent. Best-effort by contract: lifecycle must never break hook
transport.
"""

from __future__ import annotations

__all__ = ["run_remote_session_lifecycle"]


def run_remote_session_lifecycle(event_name: str, context) -> None:
    """Run the lifecycle side effect for one relayed event, never raising."""
    try:
        if event_name in ("Stop", "SessionEnd"):
            from runtime.harness.hook_runner.session_end_cleanup import (
                run_session_end_cleanup_in_process,
            )

            run_session_end_cleanup_in_process(
                context.session_id,
                executor=context.executor_family,
                event_source=event_name,
            )
        elif event_name == "SessionStart":
            from yoke_core.domain.db_helpers import connect
            from yoke_core.domain.sessions_cleanup import (
                clean_stale_harness_sessions,
            )

            conn = connect()
            try:
                clean_stale_harness_sessions(conn)
            finally:
                conn.close()
    except Exception:
        return
