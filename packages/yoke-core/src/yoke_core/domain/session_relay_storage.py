"""Persistence helpers for relay heartbeat, liveness, and bounded expiry."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
import uuid

from yoke_contracts.executor_labels import KNOWN_SURFACE_LABELS
from yoke_core.domain import db_backend, json_helper
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


def validate_heartbeat(heartbeat: RelayHeartbeat) -> RelayHeartbeat:
    if not heartbeat.relay_id.strip() or len(heartbeat.relay_id) > 128:
        raise SessionRelayError("relay_id_invalid", "relay_id must be 1-128 characters")
    try:
        machine_id = str(uuid.UUID(heartbeat.machine_id))
    except (ValueError, TypeError, AttributeError) as exc:
        raise SessionRelayError(
            "machine_id_invalid", "machine_id must be a canonical UUID"
        ) from exc
    if machine_id != heartbeat.machine_id:
        raise SessionRelayError(
            "machine_id_invalid", "machine_id must be a canonical UUID"
        )
    actor_id = int(heartbeat.actor_id)
    if actor_id <= 0:
        raise SessionRelayError(
            "relay_actor_invalid", "relay actor must be a positive integer"
        )
    unknown = sorted(set(heartbeat.surface_versions) - set(KNOWN_SURFACE_LABELS))
    if unknown:
        raise SessionRelayError(
            "surface_invalid", f"unknown relay surfaces: {', '.join(unknown)}"
        )
    relay_version = str(heartbeat.relay_version).strip()
    if not relay_version or len(relay_version) > 128:
        raise SessionRelayError(
            "relay_version_invalid", "relay version must be 1-128 characters"
        )
    for surface, version in heartbeat.surface_versions.items():
        if not str(version).strip() or len(str(version)) > 128:
            raise SessionRelayError(
                "surface_version_invalid", f"{surface} version must be 1-128 characters"
            )
    project_ids = tuple(sorted({int(value) for value in heartbeat.project_ids}))
    if any(value <= 0 for value in project_ids):
        raise SessionRelayError(
            "project_id_invalid", "relay project ids must be positive integers"
        )
    hostname = heartbeat.hostname.strip()
    if not hostname or len(hostname) > 255:
        raise SessionRelayError(
            "hostname_invalid", "relay hostname must be 1-255 characters"
        )
    return RelayHeartbeat(
        relay_id=heartbeat.relay_id.strip(),
        actor_id=actor_id,
        machine_id=machine_id,
        hostname=hostname,
        relay_version=relay_version,
        surface_versions={
            surface: str(heartbeat.surface_versions[surface]).strip()
            for surface in sorted(heartbeat.surface_versions)
        },
        project_ids=project_ids,
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
        f"SELECT actor_id,machine_id FROM session_relays WHERE relay_id={p}",
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
    connected_until = shifted(now, seconds=max(1, next_poll_seconds) * 2)
    surfaces = json_helper.dumps_compact(dict(heartbeat.surface_versions))
    projects = json_helper.dumps_compact(list(heartbeat.project_ids))
    conn.execute(
        "INSERT INTO session_relays "
        "(relay_id,actor_id,machine_id,hostname,relay_version,surface_versions,project_checkouts,"
        "first_seen_at,last_seen_at,connected_until,state) "
        f"VALUES ({','.join(p for _ in range(11))}) "
        "ON CONFLICT(relay_id) DO UPDATE SET "
        "actor_id=excluded.actor_id,machine_id=excluded.machine_id,"
        "hostname=excluded.hostname,relay_version=excluded.relay_version,"
        "surface_versions=excluded.surface_versions,"
        "project_checkouts=excluded.project_checkouts,"
        "last_seen_at=excluded.last_seen_at,"
        "connected_until=excluded.connected_until,state=excluded.state",
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


def mark_relay_job(
    conn: Any,
    *,
    relay_id: str,
    lease_id: str,
    lease_expires_at: str,
    now: str,
) -> None:
    p = marker(conn)
    cursor = conn.execute(
        "UPDATE session_relays SET lease_id=" + p + ",lease_expires_at=" + p + ","
        "last_job_at=" + p + ",state='active' WHERE relay_id=" + p,
        (lease_id, lease_expires_at, now, relay_id),
    )
    if cursor.rowcount != 1:
        raise SessionRelayError(
            "relay_missing", f"relay {relay_id!r} is not registered"
        )


def clear_relay_job(conn: Any, *, relay_id: str, lease_id: str) -> None:
    p = marker(conn)
    conn.execute(
        "UPDATE session_relays SET lease_id=NULL,lease_expires_at=NULL "
        f"WHERE relay_id={p} AND lease_id={p}",
        (relay_id, lease_id),
    )


def relay_has_live_lease(conn: Any, *, relay_id: str, now: str) -> bool:
    p = marker(conn)
    return (
        conn.execute(
            "SELECT 1 FROM session_relays "
            f"WHERE relay_id={p} AND lease_id IS NOT NULL AND lease_expires_at>{p}",
            (relay_id, now),
        ).fetchone()
        is not None
    )


def require_relay_lease(
    conn: Any,
    *,
    relay_id: str,
    lease_id: str,
    now: str,
) -> None:
    p = marker(conn)
    row = conn.execute(
        "SELECT lease_expires_at FROM session_relays "
        f"WHERE relay_id={p} AND lease_id={p} LIMIT 1",
        (relay_id, lease_id),
    ).fetchone()
    if row is None:
        raise SessionRelayError(
            "relay_lease_mismatch", "relay does not hold the reported lease"
        )
    if str(row[0] or "") <= now:
        raise SessionRelayError(
            "relay_lease_expired", "relay lease expired before the report"
        )


__all__ = [
    "clear_relay_job",
    "heartbeat_relay",
    "machine_is_idle",
    "mark_relay_job",
    "marker",
    "relay_has_live_lease",
    "require_relay_actor",
    "require_relay_lease",
    "shifted",
    "utc_now",
    "validate_heartbeat",
]
