"""Lease assigned launches together without blocking behind native wake work."""

from __future__ import annotations

from datetime import datetime

from typing import Any
from uuid import uuid4

from yoke_contracts.timestamps import parse_instant
from yoke_core.domain import db_backend
from yoke_core.domain.session_relay_storage import mark_relay_batch, marker
from yoke_core.domain.session_relay_types import (
    RelayHeartbeat,
    RelayJob,
)


def _lock(conn: Any, alias: str) -> str:
    if db_backend.connection_is_postgres(conn):
        return f" FOR UPDATE OF {alias} SKIP LOCKED"
    return ""


def _candidate_launch_ids(
    conn: Any,
    heartbeat: RelayHeartbeat,
) -> tuple[str, ...]:
    p = marker(conn)
    projects = tuple(sorted({int(value) for value in heartbeat.project_ids}))
    if not projects or not heartbeat.surface_versions:
        return ()
    project_slots = ",".join(p for _ in projects)
    surface_slots = ",".join(p for _ in heartbeat.surface_versions)
    rows = conn.execute(
        "SELECT l.launch_id FROM session_launches l "
        "WHERE l.state='assigned' "
        f"AND l.assigned_relay_id={p} AND l.assigned_machine_id={p} "
        f"AND l.project_id IN ({project_slots}) "
        f"AND l.selected_surface IN ({surface_slots}) "
        "ORDER BY l.created_at,l.launch_id" + _lock(conn, "l"),
        (
            heartbeat.relay_id,
            heartbeat.machine_id,
            *projects,
            *sorted(heartbeat.surface_versions),
        ),
    ).fetchall()
    return tuple(str(row[0]) for row in rows)


def claim_next_launch(
    conn: Any,
    heartbeat: RelayHeartbeat,
    *,
    now: datetime | str,
) -> tuple[RelayJob, ...]:
    """Lease every assigned launch; the machine checks capacity before each spawn."""
    candidates = _candidate_launch_ids(conn, heartbeat)
    conn.commit()
    if not candidates:
        return ()
    from yoke_core.domain.session_launch_execution import claim_assigned_launch
    from yoke_core.domain.session_launch_store import update_launch

    p = marker(conn)
    active = conn.execute(
        f"SELECT lease_id,lease_expires_at FROM session_relays WHERE relay_id={p}",
        (heartbeat.relay_id,),
    ).fetchone()
    batch_id = (
        str(active[0])
        if active and active[0] and parse_instant(active[1]) > parse_instant(now)
        else str(uuid4())
    )
    expires_at = (
        parse_instant(active[1])
        if active
        and active[1] is not None
        and parse_instant(active[1]) > parse_instant(now)
        else parse_instant(now)
    )
    jobs = []
    for launch_id in candidates:
        try:
            claim = claim_assigned_launch(
                conn,
                launch_id=launch_id,
                relay_id=heartbeat.relay_id,
                machine_id=heartbeat.machine_id,
                batch_id=batch_id,
                now=now,
            )
        except Exception as exc:
            if getattr(exc, "code", "") in {
                "invalid_state",
                "relay_mismatch",
                "expired",
            }:
                continue
            raise
        update_launch(conn, launch_id, spawn_hold_reason=None)
        expires_at = max(expires_at, claim.lease_expires_at)
        job = RelayJob(
            job_kind="launch",
            job_id=claim.launch.launch_id,
            lease_id=claim.lease_id,
            machine_id=heartbeat.machine_id,
            surface=claim.launch.selected_surface,
            surface_version=str(
                heartbeat.surface_versions[claim.launch.selected_surface]
            ),
            project_id=claim.launch.project_id,
            native_instruction=claim.bootstrap_prompt,
            message_id=claim.launch.message_id,
            requested_model=claim.launch.resolved_model,
            requested_reasoning_effort=claim.launch.resolved_reasoning_effort,
            requested_context_window_tokens=(
                claim.launch.resolved_context_window_tokens
            ),
            presentation=claim.launch.presentation_preference,
            session_name=claim.launch.session_name,
            deadline_at=claim.launch.deadline_at,
            launch_attestation=claim.attestation,
        )
        jobs.append(job)
    mark_relay_batch(
        conn,
        relay_id=heartbeat.relay_id,
        batch_id=batch_id,
        expires_at=expires_at,
        now=now,
    )
    conn.commit()
    return tuple(jobs)


__all__ = ["claim_next_launch"]
