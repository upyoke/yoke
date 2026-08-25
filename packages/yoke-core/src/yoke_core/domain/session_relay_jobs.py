"""Atomic launch/wake leasing and result reporting for machine relays."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from yoke_contracts.session_control.wake_instruction import native_wake_instruction
from yoke_contracts.session_control.resume import RESUMED_RUNNING_RESULT
from yoke_core.domain.session_broker_wake import direct_wake_waits_for_broker
from yoke_core.domain.session_broker_wake_adoption import claim_broker_wake_job
from yoke_core.domain.session_relay_evidence import (
    merge_redacted_evidence,
    redacted_evidence_document,
)
from yoke_core.domain.session_relay_wake_claim import claim_wake_attempt
from yoke_core.domain.session_relay_storage import (
    clear_relay_batch_when_drained,
    mark_relay_batch,
    marker,
    require_relay_batch,
)
from yoke_core.domain.session_relay_types import (
    RelayHeartbeat,
    RelayJob,
    SessionRelayError,
    WakeMode,
)
from yoke_core.domain.session_relay_private_qualification import (
    authorize_wake_candidate,
)


WAKE_REPORT_CODES = frozenset(
    "accepted failed not_found outcome_unknown thread_id_unknown "
    "unsupported_surface version_mismatch".split()
) | {RESUMED_RUNNING_RESULT}
LAUNCH_REPORT_CODES = frozenset({"native_created", "not_created", "outcome_unknown"})


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
    broker_lease_id: str | None = None,
    broker_session_id: str | None = None,
) -> RelayJob | None:
    if broker_only:
        return claim_broker_wake_job(
            conn,
            heartbeat,
            now=now,
            broker_lease_id=str(broker_lease_id or ""),
            broker_session_id=str(broker_session_id or ""),
        )
    selected: Mapping[str, Any] | None = None
    execution: tuple[str, str] = ("", "")
    qualification = None
    for row in _wake_candidates(conn, heartbeat, now=now):
        authorized, qualification = authorize_wake_candidate(
            conn, row, heartbeat, route="direct"
        )
        if authorized is None:
            continue
        selected, execution = row, authorized
        break
    if selected is None:
        return None
    message_id = str(selected["message_id"])
    session_id = str(selected["session_id"])
    project_id = int(selected["project_id"])
    claim = claim_wake_attempt(conn, candidate=selected, now=now)
    if claim is None:
        return None
    if qualification is not None:
        from yoke_core.domain.session_private_route_qualification import (
            consume_qualification_grant,
        )

        consume_qualification_grant(conn, qualification, now=now)
    mark_relay_batch(
        conn,
        relay_id=heartbeat.relay_id,
        batch_id=claim.lease_id,
        expires_at=claim.lease_expires_at,
        now=now,
    )
    conn.commit()
    return RelayJob(
        job_kind="wake",
        job_id=claim.attempt_id,
        lease_id=claim.lease_id,
        machine_id=heartbeat.machine_id,
        surface=execution[0],
        surface_version=execution[1],
        project_id=int(project_id),
        native_instruction=native_wake_instruction(message_id),
        message_id=str(message_id),
        target_session_id=str(session_id),
        target_native_thread_id=str(selected.get("native_thread_id") or "") or None,
        wake_mode=WakeMode(str(selected["wake_mode"])),
        target_liveness=str(selected["liveness"]),
        wake_route="direct",
        private_route_qualification=qualification,
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
    if str(row[2] or "") == result_code == RESUMED_RUNNING_RESULT:
        return {"attempt_id": attempt_id, "result_code": result_code}
    require_relay_batch(conn, relay_id=relay_id, now=now)
    completed_at = None if result_code == RESUMED_RUNNING_RESULT else now
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
            completed_at,
            result_code,
            str(adapter_revision or "").strip()[:128] or None,
            merge_redacted_evidence(row[3], evidence),
            attempt_id,
        ),
    )
    clear_relay_batch_when_drained(conn, relay_id=relay_id, batch_id=lease_id)
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
        "SELECT completed_at,result_code,native_session_id,batch_id "
        "FROM session_launch_attempts "
        f"WHERE launch_id={p} AND lease_id={p} AND relay_id={p}",
        (launch_id, lease_id, relay_id),
    ).fetchone()
    if prior is None:
        raise SessionRelayError(
            "attempt_missing", "this relay holds no such launch attempt lease"
        )
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
        clear_relay_batch_when_drained(
            conn,
            relay_id=relay_id,
            batch_id=str(prior[3] or ""),
        )
        conn.commit()
        return {
            "launch_id": launch_id,
            "state": str(launch[0]),
            "result_code": str(launch[1] or ""),
        }
    require_relay_batch(conn, relay_id=relay_id, now=now)
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
    clear_relay_batch_when_drained(
        conn,
        relay_id=relay_id,
        batch_id=str(prior[3] or ""),
    )
    conn.commit()
    return {
        "launch_id": launch.launch_id,
        "state": launch.state,
        "result_code": launch.result_code,
    }


__all__ = [
    "LAUNCH_REPORT_CODES",
    "WAKE_REPORT_CODES",
    "claim_wake_job",
    "report_launch_job",
    "report_wake_job",
]
