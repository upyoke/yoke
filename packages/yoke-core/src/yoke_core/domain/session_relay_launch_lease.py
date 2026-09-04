"""Lease the next assigned launch for one relay poll, spacing native creates.

One machine starts at most one native create per spacing window. The window
is measured from the most recent attempt started there, whichever relay poll
started it, so a burst of assignments drains at the pace a loaded box can
absorb. A launch held back stays ``assigned`` and says why on its own row,
so a seat reading the record sees a wait with a reason rather than a stall.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from yoke_core.domain import db_backend
from yoke_core.domain.session_relay_storage import mark_relay_batch, marker, shifted
from yoke_core.domain.session_relay_types import (
    NATIVE_SPAWN_SPACING_SECONDS,
    RelayHeartbeat,
    RelayJob,
)


def _lock(conn: Any, alias: str) -> str:
    if db_backend.connection_is_postgres(conn):
        return f" FOR UPDATE OF {alias} SKIP LOCKED"
    return ""


def _candidate_launch_id(
    conn: Any,
    heartbeat: RelayHeartbeat,
    *,
    now: str,
) -> str | None:
    p = marker(conn)
    projects = tuple(sorted({int(value) for value in heartbeat.project_ids}))
    if not projects or not heartbeat.surface_versions:
        return None
    project_slots = ",".join(p for _ in projects)
    surface_slots = ",".join(p for _ in heartbeat.surface_versions)
    row = conn.execute(
        "SELECT l.launch_id FROM session_launches l "
        "WHERE l.state='assigned' "
        f"AND l.assigned_relay_id={p} AND l.assigned_machine_id={p} "
        f"AND l.deadline_at>{p} AND l.project_id IN ({project_slots}) "
        f"AND l.selected_surface IN ({surface_slots}) "
        "ORDER BY l.created_at,l.launch_id LIMIT 1" + _lock(conn, "l"),
        (
            heartbeat.relay_id,
            heartbeat.machine_id,
            now,
            *projects,
            *sorted(heartbeat.surface_versions),
        ),
    ).fetchone()
    return str(row[0]) if row is not None else None


def spawn_hold_until(conn: Any, *, machine_id: str, now: str) -> str | None:
    """When the machine may start its next native create, or ``None`` for now."""
    p = marker(conn)
    row = conn.execute(
        f"SELECT MAX(started_at) FROM session_launch_attempts WHERE machine_id={p}",
        (machine_id,),
    ).fetchone()
    last_started = str(row[0]) if row is not None and row[0] else None
    if last_started is None:
        return None
    resume_at = shifted(last_started, seconds=NATIVE_SPAWN_SPACING_SECONDS)
    return resume_at if resume_at > now else None


def _hold_assigned_launches(
    conn: Any, heartbeat: RelayHeartbeat, *, resume_at: str
) -> None:
    p = marker(conn)
    reason = (
        f"native spawn spacing: machine {heartbeat.machine_id} started a native "
        f"create less than {NATIVE_SPAWN_SPACING_SECONDS}s ago; next create not "
        f"before {resume_at}"
    )
    conn.execute(
        f"UPDATE session_launches SET spawn_hold_reason={p} "
        f"WHERE state='assigned' AND assigned_machine_id={p}",
        (reason, heartbeat.machine_id),
    )
    conn.commit()


def claim_next_launch(
    conn: Any,
    heartbeat: RelayHeartbeat,
    *,
    now: str,
) -> tuple[RelayJob, ...]:
    """Lease the oldest eligible launch unless the machine's spacing window holds it."""
    resume_at = spawn_hold_until(conn, machine_id=heartbeat.machine_id, now=now)
    if resume_at is not None:
        _hold_assigned_launches(conn, heartbeat, resume_at=resume_at)
        return ()
    launch_id = _candidate_launch_id(conn, heartbeat, now=now)
    if launch_id is None:
        return ()
    from yoke_core.domain.session_launch_execution import claim_assigned_launch
    from yoke_core.domain.session_launch_store import update_launch

    batch_id = str(uuid4())
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
        if getattr(exc, "code", "") in {"invalid_state", "relay_mismatch", "expired"}:
            return ()
        raise
    update_launch(conn, launch_id, spawn_hold_reason=None)
    job = RelayJob(
        job_kind="launch",
        job_id=claim.launch.launch_id,
        lease_id=claim.lease_id,
        machine_id=heartbeat.machine_id,
        surface=claim.launch.selected_surface,
        surface_version=str(heartbeat.surface_versions[claim.launch.selected_surface]),
        project_id=claim.launch.project_id,
        native_instruction=claim.bootstrap_prompt,
        message_id=claim.launch.message_id,
        requested_model=claim.launch.resolved_model,
        requested_reasoning_effort=claim.launch.resolved_reasoning_effort,
        requested_context_window_tokens=(claim.launch.resolved_context_window_tokens),
        presentation=claim.launch.presentation_preference,
        session_name=claim.launch.session_name,
        deadline_at=claim.launch.deadline_at,
        launch_attestation=claim.attestation,
    )
    mark_relay_batch(
        conn,
        relay_id=heartbeat.relay_id,
        batch_id=batch_id,
        expires_at=claim.lease_expires_at,
        now=now,
    )
    conn.commit()
    return (job,)


__all__ = ["claim_next_launch", "spawn_hold_until"]
