"""Lease a bounded batch of assigned launches for one relay poll."""

from __future__ import annotations

from typing import Any, Sequence
from uuid import uuid4

from yoke_core.domain import db_backend
from yoke_core.domain.session_relay_storage import mark_relay_batch, marker
from yoke_core.domain.session_relay_types import RelayHeartbeat, RelayJob


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


def _claim_one_launch(
    conn: Any,
    heartbeat: RelayHeartbeat,
    *,
    now: str,
    batch_id: str,
) -> tuple[RelayJob, str] | None:
    """Lease the oldest eligible launch and return it with its lease horizon."""
    launch_id = _candidate_launch_id(conn, heartbeat, now=now)
    if launch_id is None:
        return None
    from yoke_core.domain.session_launch_execution import claim_assigned_launch

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
            return None
        raise
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
        requested_model=claim.launch.requested_model,
        presentation=claim.launch.presentation_preference,
        session_name=claim.launch.session_name,
        launch_attestation=claim.attestation,
    )
    return job, claim.lease_expires_at


def claim_launch_batch(
    conn: Any,
    heartbeat: RelayHeartbeat,
    *,
    now: str,
    cap: int,
) -> Sequence[RelayJob]:
    """Lease up to ``cap`` launches under one relay batch marker.

    Each launch keeps the independent lease minted for its own attempt row, so
    a partially executed batch reports job by job and strands only the jobs the
    relay never reached. The batch marker carries the shared horizon by which
    every one of them must be reported.
    """
    batch_id = str(uuid4())
    jobs: list[RelayJob] = []
    horizons: list[str] = []
    while len(jobs) < max(1, int(cap)):
        claimed = _claim_one_launch(conn, heartbeat, now=now, batch_id=batch_id)
        if claimed is None:
            break
        job, expires_at = claimed
        jobs.append(job)
        horizons.append(expires_at)
    if not jobs:
        return ()
    mark_relay_batch(
        conn,
        relay_id=heartbeat.relay_id,
        batch_id=batch_id,
        expires_at=max(horizons),
        now=now,
    )
    conn.commit()
    return tuple(jobs)


__all__ = ["claim_launch_batch"]
