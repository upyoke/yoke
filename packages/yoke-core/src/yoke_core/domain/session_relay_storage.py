"""Persistence helpers for relay heartbeat, liveness, and bounded expiry."""

from __future__ import annotations

from datetime import datetime, timedelta
import json
from typing import Any

from yoke_contracts.fleet_policy import RELAY_POLL_SECONDS
from yoke_contracts.timestamps import parse_instant
from yoke_contracts.timestamps import utc_now as utc_now
from yoke_core.domain.db_helpers import instant_parameter
from yoke_core.domain import db_backend, json_helper
from yoke_core.domain.session_relay_heartbeat_validation import validate_heartbeat
from yoke_core.domain.session_relay_types import (
    RelayHeartbeat,
    SessionRelayError,
)


def marker(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def shifted(
    timestamp: datetime | str, *, seconds: int = 0, minutes: int = 0
) -> datetime:
    return parse_instant(timestamp) + timedelta(seconds=seconds, minutes=minutes)


def heartbeat_relay(
    conn: Any,
    heartbeat: RelayHeartbeat,
    *,
    state: str,
    next_poll_seconds: int,
    now: datetime | str,
) -> datetime:
    """Upsert public machine facts and return the server-owned liveness edge."""
    heartbeat = validate_heartbeat(heartbeat)
    p = marker(conn)
    existing = conn.execute(
        "SELECT actor_id,machine_id,lease_expires_at,relay_health FROM session_relays "
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
    # Drain cadence controls throughput, not whether the persistent relay is alive.
    connected_until = shifted(
        now, seconds=max(RELAY_POLL_SECONDS, next_poll_seconds) * 2
    )
    if existing is not None and existing[2] is not None:
        connected_until = max(connected_until, parse_instant(existing[2]))
    surfaces = json_helper.dumps_compact(dict(heartbeat.surface_versions))
    confirmed_absent = json_helper.dumps_compact(
        list(heartbeat.surface_confirmed_absent)
    )
    projects = json_helper.dumps_compact(list(heartbeat.project_ids))
    plan_limits = json_helper.dumps_compact(dict(heartbeat.surface_plan_limits))
    capacity = json_helper.dumps_compact(dict(heartbeat.machine_capacity))
    health = json_helper.dumps_compact(dict(heartbeat.relay_health))
    native_models = json_helper.dumps_compact(dict(heartbeat.surface_native_models))
    credentials = json_helper.dumps_compact(dict(heartbeat.credential_presence))
    conn.execute(
        "INSERT INTO session_relays "
        "(relay_id,actor_id,machine_id,hostname,relay_version,surface_versions,"
        "surface_confirmed_absent,project_checkouts,"
        "first_seen_at,last_seen_at,connected_until,state,surface_plan_limits,"
        "machine_capacity,relay_health,surface_native_models,"
        "credential_presence) "
        f"VALUES ({','.join(p for _ in range(17))}) "
        "ON CONFLICT(relay_id) DO UPDATE SET "
        "actor_id=excluded.actor_id,machine_id=excluded.machine_id,"
        "hostname=excluded.hostname,relay_version=excluded.relay_version,"
        "surface_versions=excluded.surface_versions,"
        "surface_confirmed_absent=excluded.surface_confirmed_absent,"
        "project_checkouts=excluded.project_checkouts,"
        "last_seen_at=excluded.last_seen_at,"
        "connected_until=excluded.connected_until,state=excluded.state,"
        "surface_plan_limits=excluded.surface_plan_limits,"
        "machine_capacity=excluded.machine_capacity,"
        "relay_health=excluded.relay_health,"
        "surface_native_models=excluded.surface_native_models,"
        "credential_presence=excluded.credential_presence",
        (
            heartbeat.relay_id,
            heartbeat.actor_id,
            heartbeat.machine_id,
            heartbeat.hostname,
            heartbeat.relay_version or None,
            surfaces,
            confirmed_absent,
            projects,
            instant_parameter(conn, parse_instant(now)),
            instant_parameter(conn, parse_instant(now)),
            instant_parameter(conn, parse_instant(connected_until)),
            state,
            plan_limits,
            capacity,
            health,
            native_models,
            credentials,
        ),
    )
    from yoke_core.domain.session_relay_health_events import (
        emit_new_relay_quarantines,
    )

    try:
        previous_health = json.loads(str(existing[3] or "{}")) if existing else {}
    except (TypeError, ValueError):
        previous_health = {}
    emit_new_relay_quarantines(
        conn,
        relay_id=heartbeat.relay_id,
        machine_id=heartbeat.machine_id,
        project_ids=heartbeat.project_ids,
        previous_health=previous_health,
        relay_health=heartbeat.relay_health,
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
    now: datetime | str,
) -> bool:
    p = marker(conn)
    cutoff = shifted(now, minutes=-idle_after_minutes)
    session = conn.execute(
        "SELECT 1 FROM harness_sessions "
        f"WHERE machine_id={p} AND ended_at IS NULL "
        f"AND COALESCE(last_tool_call_at,offered_at)>={p} LIMIT 1",
        (machine_id, instant_parameter(conn, parse_instant(cutoff))),
    ).fetchone()
    if session is not None:
        return False
    recent_job = conn.execute(
        "SELECT 1 FROM session_relays "
        f"WHERE machine_id={p} AND last_job_at IS NOT NULL "
        f"AND last_job_at>={p} LIMIT 1",
        (machine_id, instant_parameter(conn, parse_instant(cutoff))),
    ).fetchone()
    return recent_job is None


def mark_relay_batch(
    conn: Any,
    *,
    relay_id: str,
    batch_id: str,
    expires_at: datetime,
    now: datetime | str,
) -> None:
    """Publish the outstanding launch group as a relay liveness hint.

    Each launch owns its deadline; this marker never authorizes a report.
    """
    p = marker(conn)
    cursor = conn.execute(
        "UPDATE session_relays SET lease_id=" + p + ",lease_expires_at=" + p + ","
        "last_job_at=" + p + ",state='active' WHERE relay_id=" + p,
        (
            batch_id,
            instant_parameter(conn, parse_instant(expires_at)),
            instant_parameter(conn, parse_instant(now)),
            relay_id,
        ),
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
    conn.execute(
        "UPDATE session_relays SET lease_id=NULL,lease_expires_at=NULL "
        f"WHERE relay_id={p} AND lease_id={p}",
        (relay_id, batch_id),
    )


def relay_has_live_batch(conn: Any, *, relay_id: str, now: datetime | str) -> bool:
    p = marker(conn)
    return (
        conn.execute(
            "SELECT 1 FROM session_relays "
            f"WHERE relay_id={p} AND lease_id IS NOT NULL AND lease_expires_at>{p}",
            (relay_id, instant_parameter(conn, parse_instant(now))),
        ).fetchone()
        is not None
    )


def relay_holds_launch(
    conn: Any, *, relay_id: str, launch_id: str, now: datetime | str
) -> bool:
    """A launch remains held until its own lease ends, regardless of other jobs."""
    from yoke_core.domain.session_launch_types import LAUNCH_LEASE_SECONDS

    p = marker(conn)
    return (
        conn.execute(
            "SELECT 1 FROM session_launch_attempts a JOIN session_launches l "
            "ON l.launch_id=a.launch_id "
            f"WHERE a.relay_id={p} AND a.launch_id={p} AND a.completed_at IS NULL "
            f"AND a.started_at>{p} AND l.deadline_at>{p} LIMIT 1",
            (
                relay_id,
                launch_id,
                instant_parameter(conn, shifted(now, seconds=-LAUNCH_LEASE_SECONDS)),
                instant_parameter(conn, parse_instant(now)),
            ),
        ).fetchone()
        is not None
    )


__all__ = [
    "clear_relay_batch_when_drained",
    "heartbeat_relay",
    "machine_is_idle",
    "mark_relay_batch",
    "marker",
    "relay_has_live_batch",
    "relay_holds_launch",
    "require_relay_actor",
    "shifted",
    "utc_now",
    "validate_heartbeat",
]
