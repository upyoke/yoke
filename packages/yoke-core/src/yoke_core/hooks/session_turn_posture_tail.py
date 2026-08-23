"""Best-effort persistence for accepted native lifecycle hook posture."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from yoke_core.domain.session_turn_posture import (
    accepted_hook_posture,
    stamp_turn_posture,
)


def persist_accepted_hook_turn_posture(
    *,
    event_name: str,
    session_id: str,
    observed_at: datetime | None,
    final_outcome: str,
    timed_out: bool,
    failed: bool,
    connection_factory: Callable[[], Any] | None = None,
) -> bool:
    """Persist one aggregate-accepted hook observation without breaking hooks."""
    posture = accepted_hook_posture(
        event_name,
        final_outcome=final_outcome,
        timed_out=timed_out,
        failed=failed,
    )
    if posture is None or not session_id or observed_at is None:
        return False
    if connection_factory is None:
        from yoke_core.domain.db_helpers import connect

        connection_factory = connect
    conn = None
    try:
        conn = connection_factory()
        changed = stamp_turn_posture(
            conn,
            session_id=session_id,
            posture=posture,
            observed_at=observed_at,
        )
        conn.commit()
        return changed
    except Exception:  # noqa: BLE001 - lifecycle state must not break native hooks
        if conn is not None:
            try:
                conn.rollback()
            except Exception:  # noqa: BLE001
                pass
        return False
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass


__all__ = ["persist_accepted_hook_turn_posture"]
