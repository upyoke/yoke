"""Atomic launch/wake leasing and result reporting for machine relays."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from yoke_contracts.session_control.wake_instruction import native_wake_instruction
from yoke_core.domain import db_backend
from yoke_core.domain.session_broker_wake import direct_wake_waits_for_broker
from yoke_core.domain.session_broker_wake_adoption import claim_broker_wake_job
from yoke_core.domain.session_relay_evidence import (
    merge_redacted_evidence,
    redacted_evidence_document,
)
from yoke_core.domain.session_relay_wake_claim import claim_wake_attempt
from yoke_core.domain.session_relay_storage import (
    clear_relay_job,
    mark_relay_job,
    marker,
    require_relay_lease,
)
from yoke_core.domain.session_relay_types import (
    RelayHeartbeat,
    RelayJob,
    SessionRelayError,
    WakeMode,
)
from yoke_core.domain.session_relay_versions import wake_candidate_supported


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
LAUNCH_REPORT_CODES = frozenset({"native_created", "not_created", "outcome_unknown"})


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
        surface=claim.launch.selected_surface,
        surface_version=str(heartbeat.surface_versions[claim.launch.selected_surface]),
        project_id=claim.launch.project_id,
        native_instruction=claim.bootstrap_prompt,
        message_id=claim.launch.message_id,
        requested_model=claim.launch.requested_model,
        presentation=claim.launch.presentation_preference,
        launch_attestation=claim.attestation,
    )


def _wake_candidates(
    conn: Any,
    heartbeat: RelayHeartbeat,
    *,
    now: str,
) -> Sequence[Mapping[str, Any]]:
    from yoke_core.domain.session_message_types import parse_timestamp
    from yoke_core.domain.session_message_wake import wake_eligible_recipients

    projects = tuple(sorted({int(value) for value in heartbeat.project_ids}))
    if not projects:
        return ()
    return tuple(
        row
        for row in wake_eligible_recipients(conn, now=parse_timestamp(now))
        if row.get("machine_id") == heartbeat.machine_id
        and int(row["project_id"]) in projects
        and not direct_wake_waits_for_broker(
            conn,
            message_id=str(row["message_id"]),
            session_id=str(row["session_id"]),
            now=now,
        )
    )[:25]


def claim_wake_job(
    conn: Any,
    heartbeat: RelayHeartbeat,
    *,
    now: str,
    broker_only: bool = False,
) -> RelayJob | None:
    brokered = claim_broker_wake_job(conn, heartbeat, now=now)
    if brokered is not None:
        return brokered
    if broker_only:
        return None
    selected = None
    for row in _wake_candidates(conn, heartbeat, now=now):
        if not wake_candidate_supported(row, heartbeat.surface_versions):
            continue
        selected = row
        break
    if selected is None:
        return None
    message_id = str(selected["message_id"])
    session_id = str(selected["session_id"])
    project_id = int(selected["project_id"])
    surface = str(selected["executor_surface"])
    claim = claim_wake_attempt(conn, candidate=selected, now=now)
    if claim is None:
        return None
    mark_relay_job(
        conn,
        relay_id=heartbeat.relay_id,
        lease_id=claim.lease_id,
        lease_expires_at=claim.lease_expires_at,
        now=now,
    )
    conn.commit()
    return RelayJob(
        job_kind="wake",
        job_id=claim.attempt_id,
        lease_id=claim.lease_id,
        machine_id=heartbeat.machine_id,
        surface=str(surface),
        surface_version=str(heartbeat.surface_versions[surface]),
        project_id=int(project_id),
        native_instruction=native_wake_instruction(message_id),
        message_id=str(message_id),
        target_session_id=str(session_id),
        wake_mode=WakeMode(str(selected["wake_mode"])),
        target_liveness=str(selected["liveness"]),
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
        "SELECT lease_id,completed_at,result_code,evidence "
        "FROM session_message_attempts "
        f"WHERE attempt_id={p} AND attempt_kind IN ('wake_relay','wake_broker')",
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
        "UPDATE session_message_attempts SET completed_at="
        + p
        + ",result_code="
        + p
        + ",adapter_revision="
        + p
        + ",evidence="
        + p
        + f" WHERE attempt_id={p}",
        (
            now,
            result_code,
            str(adapter_revision or "").strip()[:128] or None,
            merge_redacted_evidence(row[3], evidence),
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
            f"SELECT state,result_code FROM session_launches WHERE launch_id={p}",
            (launch_id,),
        ).fetchone()
        clear_relay_job(conn, relay_id=relay_id, lease_id=lease_id)
        conn.commit()
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
