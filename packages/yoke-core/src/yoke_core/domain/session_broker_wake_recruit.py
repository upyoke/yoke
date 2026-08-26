"""Recruitment policy for one-hop broker wakes.

A live persistent relay already holds the machine lock, so a peer
``serve-once --broker`` can only contend it. When a hop is still needed,
prefer a CLI worker over an operator-facing desktop session.
"""

from __future__ import annotations

from typing import Any, Mapping

from yoke_core.domain.session_relay_storage import marker


WORKER_SURFACE_SUFFIX = "-cli"


def machine_has_fresh_relay(conn: Any, machine_id: str, now: str) -> bool:
    """True when this machine's persistent relay heartbeat is still ahead."""
    if not machine_id:
        return False
    placeholder = marker(conn)
    return (
        conn.execute(
            "SELECT 1 FROM session_relays "
            f"WHERE machine_id={placeholder} AND state IN ('active','idle') "
            f"AND connected_until>{placeholder} LIMIT 1",
            (machine_id, now),
        ).fetchone()
        is not None
    )


def broker_surface_is_worker(surface: str | None) -> bool:
    return str(surface or "").endswith(WORKER_SURFACE_SUFFIX)


def preferred_worker_available(
    conn: Any,
    *,
    machine_id: str,
    exclude_session_ids: set[str],
) -> bool:
    """True when a non-ended CLI session on this machine can take the hop."""
    if not machine_id:
        return False
    placeholder = marker(conn)
    rows = conn.execute(
        "SELECT session_id,executor_surface FROM harness_sessions "
        f"WHERE machine_id={placeholder} AND ended_at IS NULL",
        (machine_id,),
    ).fetchall()
    excluded = {str(value) for value in exclude_session_ids}
    return any(
        str(row[0]) not in excluded and broker_surface_is_worker(row[1]) for row in rows
    )


def should_defer_operator_facing_broker(
    conn: Any,
    *,
    broker: Mapping[str, Any],
    exclude_session_ids: set[str],
) -> bool:
    """Skip a desktop/UX recruit when a CLI worker on the same machine can hop."""
    if broker_surface_is_worker(broker.get("executor_surface")):
        return False
    return preferred_worker_available(
        conn,
        machine_id=str(broker.get("machine_id") or ""),
        exclude_session_ids=exclude_session_ids | {str(broker.get("session_id") or "")},
    )


__all__ = [
    "WORKER_SURFACE_SUFFIX",
    "broker_surface_is_worker",
    "machine_has_fresh_relay",
    "preferred_worker_available",
    "should_defer_operator_facing_broker",
]
