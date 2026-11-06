"""Best-effort persistence for accepted native lifecycle hook posture."""

from __future__ import annotations

from datetime import datetime
from collections.abc import Mapping
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


def persist_authorization_denied_turn_end(
    *,
    event_name: str,
    session_id: str,
    actor_id: int,
    observed_at: datetime,
    connection_factory: Callable[[], Any] | None = None,
) -> str | None:
    """Record an owned turn end even when checkout authorization refused work.

    A project refusal does not ask the harness to continue the turn. This
    observation grants no registration, project access or cleanup authority.
    Policy Stop holds still go through aggregate-accepted persistence above.
    """
    if event_name not in {"Stop", "SessionEnd"}:
        return None
    if connection_factory is None:
        from yoke_core.domain.db_helpers import connect

        connection_factory = connect
    from yoke_core.domain import db_backend

    try:
        with connection_factory() as conn:
            marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
            row = conn.execute(
                f"SELECT actor_id FROM harness_sessions WHERE session_id={marker}",
                (session_id,),
            ).fetchone()
            owner = (
                row.get("actor_id")
                if isinstance(row, Mapping)
                else row[0]
                if row
                else None
            )
            if owner != actor_id:
                return (
                    "turn_posture_owner_unverified: relay through the connection "
                    "whose actor owns the registered session."
                )
            stamp_turn_posture(
                conn,
                session_id=session_id,
                posture="waiting",
                observed_at=observed_at,
            )
            conn.commit()
    except Exception:  # noqa: BLE001 - keep the original project refusal visible
        return (
            "turn_posture_unavailable: restore project authorization and retry "
            "the hook through yoke hook evaluate; the relay can also recover "
            "Codex posture from its completed turn record."
        )
    return None


__all__ = [
    "persist_accepted_hook_turn_posture",
    "persist_authorization_denied_turn_end",
]
