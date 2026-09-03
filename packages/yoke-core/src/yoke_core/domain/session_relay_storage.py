"""Persistence helpers for relay heartbeat, liveness, and bounded expiry."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from yoke_contracts.session_control.wake_delivery import (
    WAKE_DELIVERY_UNVERIFIED_RESULTS,
)
from yoke_core.domain import db_backend, json_helper
from yoke_core.domain.session_relay_heartbeat_validation import validate_heartbeat
from yoke_core.domain.session_relay_types import (
    RelayHeartbeat,
    SessionRelayError,
)


def marker(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def shifted(timestamp: str, *, seconds: int = 0, minutes: int = 0) -> str:
    parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    return (parsed + timedelta(seconds=seconds, minutes=minutes)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def heartbeat_relay(
    conn: Any,
    heartbeat: RelayHeartbeat,
    *,
    state: str,
    next_poll_seconds: int,
    now: str,
) -> str:
    """Upsert public machine facts and return the server-owned liveness edge."""
    heartbeat = validate_heartbeat(heartbeat)
    p = marker(conn)
    existing = conn.execute(
        "SELECT actor_id,machine_id,lease_expires_at FROM session_relays "
        f"WHERE relay_id={p}",
        (heartbeat.relay_id,),
    ).fetchone()
    if existing is not None and int(existing[0]) != heartbeat.actor_id:
        raise SessionRelayError(
            "relay_actor_mismatch",
            "an existing relay id belongs to a different authenticated actor",
        )
    if existing is not None and str(existing[1]) != heartbeat.machine_id:
        raise SessionRelayError(
            "relay_machine_mismatch",
            "an existing relay id cannot move to a different machine",
        )
    # A relay executing a batch is silent for as long as its native creates
    # take, which outlasts a poll interval. It owes a report by the batch
    # horizon, so it stays connected at least that long — otherwise it drops
    # out of the eligible roster mid-burst and new launches find no relay.
    connected_until = max(
        shifted(now, seconds=max(1, next_poll_seconds) * 2),
        str(existing[2] or "") if existing is not None else "",
    )
    surfaces = json_helper.dumps_compact(dict(heartbeat.surface_versions))
    projects = json_helper.dumps_compact(list(heartbeat.project_ids))
    plan_limits = json_helper.dumps_compact(dict(heartbeat.surface_plan_limits))
    capacity = json_helper.dumps_compact(dict(heartbeat.machine_capacity))
    preferred = json_helper.dumps_compact(dict(heartbeat.preferred_session_models))
    conn.execute(
        "INSERT INTO session_relays "
        "(relay_id,actor_id,machine_id,hostname,relay_version,surface_versions,project_checkouts,"
        "first_seen_at,last_seen_at,connected_until,state,surface_plan_limits,"
        "machine_capacity,preferred_session_models) "
        f"VALUES ({','.join(p for _ in range(14))}) "
        "ON CONFLICT(relay_id) DO UPDATE SET "
        "actor_id=excluded.actor_id,machine_id=excluded.machine_id,"
        "hostname=excluded.hostname,relay_version=excluded.relay_version,"
        "surface_versions=excluded.surface_versions,"
        "project_checkouts=excluded.project_checkouts,"
        "last_seen_at=excluded.last_seen_at,"
        "connected_until=excluded.connected_until,state=excluded.state,"
        "surface_plan_limits=excluded.surface_plan_limits,"
        "machine_capacity=excluded.machine_capacity,"
        "preferred_session_models=excluded.preferred_session_models",
        (
            heartbeat.relay_id,
            heartbeat.actor_id,
            heartbeat.machine_id,
            heartbeat.hostname,
            heartbeat.relay_version or None,
            surfaces,
            projects,
            now,
            now,
            connected_until,
            state,
            plan_limits,
            capacity,
            preferred,
        ),
    )
    conn.commit()
    return connected_until


def require_relay_actor(conn: Any, *, relay_id: str, actor_id: int) -> None:
    p = marker(conn)
    row = conn.execute(
        f"SELECT actor_id FROM session_relays WHERE relay_id={p}",
        (relay_id,),
    ).fetchone()
    if row is None:
        raise SessionRelayError(
            "relay_missing", f"relay {relay_id!r} is not registered"
        )
    if int(row[0]) != int(actor_id):
        raise SessionRelayError(
            "relay_actor_mismatch",
            "relay report actor does not own the registered relay",
        )


def machine_is_idle(
    conn: Any,
    *,
    machine_id: str,
    idle_after_minutes: int,
    now: str,
) -> bool:
    p = marker(conn)
    cutoff = shifted(now, minutes=-idle_after_minutes)
    session = conn.execute(
        "SELECT 1 FROM harness_sessions "
        f"WHERE machine_id={p} AND ended_at IS NULL "
        f"AND COALESCE(last_tool_call_at,offered_at)>={p} LIMIT 1",
        (machine_id, cutoff),
    ).fetchone()
    if session is not None:
        return False
    recent_job = conn.execute(
        "SELECT 1 FROM session_relays "
        f"WHERE machine_id={p} AND last_job_at IS NOT NULL "
        f"AND last_job_at>={p} LIMIT 1",
        (machine_id, cutoff),
    ).fetchone()
    return recent_job is None


def mark_relay_batch(
    conn: Any,
    *,
    relay_id: str,
    batch_id: str,
    expires_at: str,
    now: str,
) -> None:
    """Record that this relay owns one outstanding batch until ``expires_at``.

    A batch spans every job leased by a single poll. Each job keeps its own
    lease id on its attempt row; this marker carries only the relay-level
    ownership and the horizon by which the whole batch must be reported.
    """
    p = marker(conn)
    cursor = conn.execute(
        "UPDATE session_relays SET lease_id=" + p + ",lease_expires_at=" + p + ","
        "last_job_at=" + p + ",state='active' WHERE relay_id=" + p,
        (batch_id, expires_at, now, relay_id),
    )
    if cursor.rowcount != 1:
        raise SessionRelayError(
            "relay_missing", f"relay {relay_id!r} is not registered"
        )


def clear_relay_batch_when_drained(
    conn: Any,
    *,
    relay_id: str,
    batch_id: str,
) -> None:
    """Release this batch's marker once none of its jobs are outstanding.

    The guard names the batch explicitly: a relay that has already moved on to
    a newer batch must keep that newer marker, whatever happens to the jobs of
    an abandoned one.
    """
    if not batch_id:
        return
    p = marker(conn)
    launch = conn.execute(
        "SELECT 1 FROM session_launch_attempts "
        f"WHERE batch_id={p} AND completed_at IS NULL LIMIT 1",
        (batch_id,),
    ).fetchone()
    if launch is not None:
        return
    unverified = tuple(sorted(WAKE_DELIVERY_UNVERIFIED_RESULTS))
    wake = conn.execute(
        "SELECT 1 FROM session_message_attempts "
        f"WHERE lease_id={p} AND attempt_kind IN ('wake_relay','wake_broker') "
        "AND completed_at IS NULL AND (result_code IS NULL OR result_code NOT IN ("
        + ",".join(p for _ in unverified)
        + ")) LIMIT 1",
        (batch_id, *unverified),
    ).fetchone()
    if wake is not None:
        return
    termination = conn.execute(
        "SELECT 1 FROM session_termination_reaps "
        f"WHERE lease_id={p} AND state='leased' LIMIT 1",
        (batch_id,),
    ).fetchone()
    if termination is not None:
        return
    conn.execute(
        "UPDATE session_relays SET lease_id=NULL,lease_expires_at=NULL "
        f"WHERE relay_id={p} AND lease_id={p}",
        (relay_id, batch_id),
    )


def relay_has_live_batch(conn: Any, *, relay_id: str, now: str) -> bool:
    p = marker(conn)
    return (
        conn.execute(
            "SELECT 1 FROM session_relays "
            f"WHERE relay_id={p} AND lease_id IS NOT NULL AND lease_expires_at>{p}",
            (relay_id, now),
        ).fetchone()
        is not None
    )


def relay_holds_batch(conn: Any, *, relay_id: str, batch_id: str, now: str) -> bool:
    """Report whether this exact batch is the one the relay still owns."""
    if not batch_id:
        return False
    p = marker(conn)
    return (
        conn.execute(
            "SELECT 1 FROM session_relays "
            f"WHERE relay_id={p} AND lease_id={p} AND lease_expires_at>{p}",
            (relay_id, batch_id, now),
        ).fetchone()
        is not None
    )


def require_relay_batch(conn: Any, *, relay_id: str, now: str) -> None:
    """Refuse a report once the batch horizon has passed.

    Which job the report belongs to is settled by the attempt row's own lease
    id; this guard only establishes that the relay still owns the batch it is
    reporting under.
    """
    p = marker(conn)
    row = conn.execute(
        "SELECT lease_expires_at FROM session_relays "
        f"WHERE relay_id={p} AND lease_id IS NOT NULL LIMIT 1",
        (relay_id,),
    ).fetchone()
    if row is None:
        raise SessionRelayError(
            "relay_lease_mismatch", "relay does not hold an outstanding batch"
        )
    if str(row[0] or "") <= now:
        raise SessionRelayError(
            "relay_lease_expired", "relay batch expired before the report"
        )


__all__ = [
    "clear_relay_batch_when_drained",
    "heartbeat_relay",
    "machine_is_idle",
    "mark_relay_batch",
    "marker",
    "relay_has_live_batch",
    "relay_holds_batch",
    "require_relay_actor",
    "require_relay_batch",
    "shifted",
    "utc_now",
    "validate_heartbeat",
]
