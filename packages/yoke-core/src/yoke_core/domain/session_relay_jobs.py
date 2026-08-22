"""Atomic launch/wake leasing and result reporting for machine relays."""

from __future__ import annotations

from typing import Any, Mapping, Sequence
import uuid

from yoke_core.domain import db_backend
from yoke_core.domain.session_relay_evidence import (
    redacted_evidence,
    redacted_evidence_document,
)
from yoke_core.domain.session_relay_storage import (
    clear_relay_job,
    mark_relay_job,
    marker,
    require_relay_lease,
    shifted,
)
from yoke_core.domain.session_relay_types import (
    RelayHeartbeat,
    RelayJob,
    SessionRelayError,
    WAKE_LEASE_SECONDS,
)
from yoke_core.domain.session_relay_versions import surface_operation_supported


WAKE_REPORT_CODES = frozenset(
    {
        "accepted",
        "failed",
        "not_found",
        "outcome_unknown",
        "unsupported_surface",
        "version_mismatch",
    }
)
LAUNCH_REPORT_CODES = frozenset(
    {"native_created", "not_created", "outcome_unknown"}
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
        f"AND l.requested_surface IN ({surface_slots}) "
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


def claim_launch_job(
    conn: Any,
    heartbeat: RelayHeartbeat,
    *,
    now: str,
) -> RelayJob | None:
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
            now=now,
        )
    except Exception as exc:
        if getattr(exc, "code", "") in {"invalid_state", "relay_mismatch", "expired"}:
            return None
        raise
    mark_relay_job(
        conn,
        relay_id=heartbeat.relay_id,
        lease_id=claim.lease_id,
        lease_expires_at=claim.lease_expires_at,
        now=now,
    )
    conn.commit()
    return RelayJob(
        job_kind="launch",
        job_id=claim.launch.launch_id,
        lease_id=claim.lease_id,
        machine_id=heartbeat.machine_id,
        surface=claim.launch.requested_surface,
        project_id=claim.launch.project_id,
        native_instruction=claim.bootstrap_prompt,
        message_id=claim.launch.message_id,
        launch_attestation=claim.attestation,
    )


def _wake_candidates(
    conn: Any,
    heartbeat: RelayHeartbeat,
    *,
    max_attempts: int,
    now: str,
) -> Sequence[Any]:
    p = marker(conn)
    projects = tuple(sorted({int(value) for value in heartbeat.project_ids}))
    if not projects:
        return ()
    project_slots = ",".join(p for _ in projects)
    return conn.execute(
        "SELECT r.message_id,r.session_id,r.project_id,r.executor_surface,"
        "r.executor_version FROM session_message_recipients r "
        "JOIN session_messages m ON m.message_id=r.message_id "
        "JOIN harness_sessions s ON s.session_id=r.session_id "
        "WHERE r.state='pending' AND r.machine_id=" + p + " "
        f"AND r.project_id IN ({project_slots}) AND r.wake_after<={p} "
        f"AND r.wake_attempt_count<{p} AND m.expires_at>{p} "
        "AND m.cancelled_at IS NULL "
        "AND (s.last_tool_call_at IS NULL OR s.last_tool_call_at<r.created_at) "
        "ORDER BY r.created_at,r.message_id,r.session_id LIMIT 25"
        + _lock(conn, "r"),
        (heartbeat.machine_id, *projects, now, max_attempts, now),
    ).fetchall()


def claim_wake_job(
    conn: Any,
    heartbeat: RelayHeartbeat,
    *,
    max_attempts: int,
    now: str,
) -> RelayJob | None:
    selected = None
    for row in _wake_candidates(
        conn, heartbeat, max_attempts=max_attempts, now=now
    ):
        surface = str(row[3] or "")
        target_version = str(row[4] or "")
        relay_version = heartbeat.surface_versions.get(surface)
        if not surface_operation_supported(surface, target_version, "message_stopped"):
            continue
        if not surface_operation_supported(surface, relay_version, "message_stopped"):
            continue
        selected = row
        break
    if selected is None:
        return None
    message_id, session_id, project_id, surface, _version = selected
    attempt_id = str(uuid.uuid4())
    lease_id = str(uuid.uuid4())
    lease_expires_at = shifted(now, seconds=WAKE_LEASE_SECONDS)
    p = marker(conn)
    updated = conn.execute(
        "UPDATE session_message_recipients SET wake_attempt_count="
        "wake_attempt_count+1,last_wake_at=" + p + " "
        f"WHERE message_id={p} AND session_id={p} AND state='pending'",
        (now, message_id, session_id),
    )
    if updated.rowcount != 1:
        conn.rollback()
        return None
    conn.execute(
        "INSERT INTO session_message_attempts "
        "(attempt_id,message_id,target_session_id,attempt_kind,lease_id,"
        "started_at,evidence) "
        f"VALUES ({','.join(p for _ in range(7))})",
        (
            attempt_id,
            message_id,
            session_id,
            "wake_relay",
            lease_id,
            now,
            redacted_evidence(None),
        ),
    )
    mark_relay_job(
        conn,
        relay_id=heartbeat.relay_id,
        lease_id=lease_id,
        lease_expires_at=lease_expires_at,
        now=now,
    )
    conn.commit()
    return RelayJob(
        job_kind="wake",
        job_id=attempt_id,
        lease_id=lease_id,
        machine_id=heartbeat.machine_id,
        surface=str(surface),
        project_id=int(project_id),
        native_instruction=f"Yoke message {message_id}: check your Yoke messages.",
        message_id=str(message_id),
        target_session_id=str(session_id),
    )


def report_wake_job(
    conn: Any,
    *,
    relay_id: str,
    attempt_id: str,
    lease_id: str,
    result_code: str,
    adapter_revision: str | None,
    evidence: Mapping[str, Any] | None,
    now: str,
) -> dict[str, Any]:
    if result_code not in WAKE_REPORT_CODES:
        raise SessionRelayError("result_invalid", "unknown wake relay result code")
    p = marker(conn)
    row = conn.execute(
        "SELECT lease_id,completed_at,result_code FROM session_message_attempts "
        f"WHERE attempt_id={p} AND attempt_kind='wake_relay'",
        (attempt_id,),
    ).fetchone()
    if row is None:
        raise SessionRelayError("attempt_missing", "wake attempt does not exist")
    if str(row[0] or "") != lease_id:
        raise SessionRelayError("lease_mismatch", "wake attempt lease does not match")
    if row[1] is not None:
        if str(row[2] or "") == result_code:
            return {"attempt_id": attempt_id, "result_code": result_code}
        raise SessionRelayError("report_conflict", "wake attempt was already reported")
    require_relay_lease(
        conn,
        relay_id=relay_id,
        lease_id=lease_id,
        now=now,
    )
    conn.execute(
        "UPDATE session_message_attempts SET completed_at=" + p + ",result_code="
        + p + ",adapter_revision=" + p + ",evidence=" + p
        + f" WHERE attempt_id={p}",
        (
            now,
            result_code,
            str(adapter_revision or "").strip()[:128] or None,
            redacted_evidence(evidence),
            attempt_id,
        ),
    )
    clear_relay_job(conn, relay_id=relay_id, lease_id=lease_id)
    conn.commit()
    return {"attempt_id": attempt_id, "result_code": result_code}


def report_launch_job(
    conn: Any,
    *,
    relay_id: str,
    launch_id: str,
    lease_id: str,
    result_code: str,
    native_session_id: str | None,
    adapter_revision: str | None,
    evidence: Mapping[str, Any] | None,
    now: str,
) -> dict[str, Any]:
    if result_code not in LAUNCH_REPORT_CODES:
        raise SessionRelayError("result_invalid", "unknown launch relay result code")
    p = marker(conn)
    prior = conn.execute(
        "SELECT completed_at,result_code,native_session_id "
        "FROM session_launch_attempts "
        f"WHERE launch_id={p} AND lease_id={p}",
        (launch_id, lease_id),
    ).fetchone()
    if prior is None:
        raise SessionRelayError("attempt_missing", "launch attempt does not exist")
    if prior[0] is not None:
        if str(prior[1] or "") != result_code or str(prior[2] or "") != str(
            native_session_id or ""
        ):
            raise SessionRelayError(
                "report_conflict", "launch attempt was already reported"
            )
        launch = conn.execute(
            "SELECT state,result_code FROM session_launches "
            f"WHERE launch_id={p}",
            (launch_id,),
        ).fetchone()
        return {
            "launch_id": launch_id,
            "state": str(launch[0]),
            "result_code": str(launch[1] or ""),
        }
    require_relay_lease(
        conn,
        relay_id=relay_id,
        lease_id=lease_id,
        now=now,
    )
    from yoke_core.domain.session_launch_execution import report_launch_attempt

    launch = report_launch_attempt(
        conn,
        launch_id=launch_id,
        lease_id=lease_id,
        result_code=result_code,
        native_session_id=native_session_id,
        adapter_revision=adapter_revision,
        evidence=redacted_evidence_document(evidence),
        now=now,
    )
    clear_relay_job(conn, relay_id=relay_id, lease_id=lease_id)
    conn.commit()
    return {
        "launch_id": launch.launch_id,
        "state": launch.state,
        "result_code": launch.result_code,
    }


__all__ = [
    "LAUNCH_REPORT_CODES",
    "WAKE_REPORT_CODES",
    "claim_launch_job",
    "claim_wake_job",
    "report_launch_job",
    "report_wake_job",
]
