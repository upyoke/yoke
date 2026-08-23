"""Adopt a rendered peer wake request into the existing native relay path."""

from __future__ import annotations

from typing import Any, Mapping

from yoke_contracts.session_control.wake_instruction import (
    native_wake_instruction,
    native_wake_instruction_sha256,
)
from yoke_core.domain import db_backend
from yoke_core.domain.session_broker_wake_settlement import (
    settle_broker_wake_losses,
)
from yoke_core.domain.session_message_types import parse_timestamp
from yoke_core.domain.session_message_wake import wake_eligible_recipients
from yoke_core.domain.session_relay_evidence import merge_redacted_evidence
from yoke_core.domain.session_relay_storage import (
    mark_relay_job,
    marker,
    shifted,
)
from yoke_core.domain.session_relay_types import (
    RelayHeartbeat,
    RelayJob,
    WAKE_LEASE_SECONDS,
    WakeMode,
)
from yoke_core.domain.session_relay_versions import wake_candidate_supported


def _lock(conn: Any, alias: str) -> str:
    if db_backend.connection_is_postgres(conn):
        return f" FOR UPDATE OF {alias}"
    return ""


def _begin(conn: Any) -> None:
    if not db_backend.connection_is_postgres(conn) and not bool(
        getattr(conn, "in_transaction", False)
    ):
        conn.execute("BEGIN IMMEDIATE")


def _same(value: Any, expected: Any) -> bool:
    return str(value or "") == str(expected or "")


def _close_with_code(conn: Any, attempt_id: str, result_code: str, now: str) -> None:
    from yoke_core.domain.session_broker_wake_settlement import (
        close_broker_attempt,
    )

    _begin(conn)
    close_broker_attempt(
        conn,
        attempt_id=attempt_id,
        result_code=result_code,
        now=now,
    )
    conn.commit()


def _adopt_attempt(
    conn: Any,
    *,
    attempt_id: str,
    candidate: Mapping[str, Any],
    heartbeat: RelayHeartbeat,
    now: str,
) -> RelayJob | None:
    p = marker(conn)
    _begin(conn)
    try:
        attempt = conn.execute(
            "SELECT lease_id,result_code,completed_at,evidence "
            "FROM session_message_attempts a "
            f"WHERE attempt_id={p} AND attempt_kind='wake_broker'" + _lock(conn, "a"),
            (attempt_id,),
        ).fetchone()
        receipt = conn.execute(
            "SELECT r.state,r.wake_attempt_count,r.last_wake_at,"
            "r.injection_lease_id,hs.machine_id,hs.turn_posture,hs.turn_posture_at "
            "FROM session_message_recipients r JOIN harness_sessions hs "
            "ON hs.session_id=r.session_id "
            f"WHERE r.message_id={p} AND r.session_id={p}" + _lock(conn, "r"),
            (candidate["message_id"], candidate["session_id"]),
        ).fetchone()
        if attempt is None or receipt is None:
            conn.rollback()
            return None
        checks = (
            attempt[2] is None,
            str(attempt[1] or "") == "broker_instructed",
            _same(receipt[0], candidate.get("state")),
            int(receipt[1] or 0) == int(candidate.get("wake_attempt_count") or 0),
            _same(receipt[2], candidate.get("last_wake_at")),
            _same(receipt[3], candidate.get("injection_lease_id")),
            _same(receipt[4], heartbeat.machine_id),
            _same(receipt[5], candidate.get("turn_posture")),
            _same(receipt[6], candidate.get("turn_posture_at")),
        )
        if not all(checks):
            conn.rollback()
            return None
        conn.execute(
            "UPDATE session_message_recipients SET wake_attempt_count="
            "wake_attempt_count+1,last_wake_at="
            + p
            + f" WHERE message_id={p} AND session_id={p}",
            (now, candidate["message_id"], candidate["session_id"]),
        )
        message_id = str(candidate["message_id"])
        instruction = native_wake_instruction(message_id)
        conn.execute(
            "UPDATE session_message_attempts SET result_code='broker_native_claimed',"
            "evidence=" + p + f" WHERE attempt_id={p}",
            (
                merge_redacted_evidence(
                    attempt[3],
                    {
                        "native_instruction_sha256": native_wake_instruction_sha256(
                            message_id
                        )
                    },
                ),
                attempt_id,
            ),
        )
        lease_id = str(attempt[0])
        mark_relay_job(
            conn,
            relay_id=heartbeat.relay_id,
            lease_id=lease_id,
            lease_expires_at=shifted(now, seconds=WAKE_LEASE_SECONDS),
            now=now,
        )
        conn.commit()
        surface = str(candidate["executor_surface"])
        return RelayJob(
            job_kind="wake",
            job_id=attempt_id,
            lease_id=lease_id,
            machine_id=heartbeat.machine_id,
            surface=surface,
            surface_version=str(heartbeat.surface_versions[surface]),
            project_id=int(candidate["project_id"]),
            native_instruction=instruction,
            message_id=message_id,
            target_session_id=str(candidate["session_id"]),
            wake_mode=WakeMode(str(candidate["wake_mode"])),
            target_liveness=str(candidate["liveness"]),
        )
    except Exception:
        conn.rollback()
        raise


def claim_broker_wake_job(
    conn: Any, heartbeat: RelayHeartbeat, *, now: str
) -> RelayJob | None:
    settle_broker_wake_losses(conn, now=parse_timestamp(now))
    p = marker(conn)
    rows = conn.execute(
        "SELECT a.attempt_id,a.message_id,a.target_session_id "
        "FROM session_message_attempts a JOIN session_message_recipients r "
        "ON r.message_id=a.message_id AND r.session_id=a.target_session_id "
        f"WHERE a.attempt_kind='wake_broker' AND a.completed_at IS NULL "
        f"AND a.result_code='broker_instructed' AND r.machine_id={p} "
        "ORDER BY a.started_at,a.attempt_id LIMIT 25",
        (heartbeat.machine_id,),
    ).fetchall()
    projects = {int(value) for value in heartbeat.project_ids}
    for attempt_id, message_id, session_id in rows:
        candidates = wake_eligible_recipients(
            conn,
            now=parse_timestamp(now),
            bypass_waiting_retry_cooldown=True,
            ignore_attempt_id=str(attempt_id),
        )
        candidate = next(
            (
                row
                for row in candidates
                if str(row["message_id"]) == str(message_id)
                and str(row["session_id"]) == str(session_id)
            ),
            None,
        )
        if candidate is None:
            _close_with_code(conn, str(attempt_id), "broker_target_changed", now)
            continue
        if int(candidate["project_id"]) not in projects:
            continue
        if not wake_candidate_supported(candidate, heartbeat.surface_versions):
            if str(candidate["executor_surface"]) in heartbeat.surface_versions:
                _close_with_code(conn, str(attempt_id), "version_mismatch", now)
            continue
        claimed = _adopt_attempt(
            conn,
            attempt_id=str(attempt_id),
            candidate=candidate,
            heartbeat=heartbeat,
            now=now,
        )
        if claimed is not None:
            return claimed
    return None


__all__ = ["claim_broker_wake_job"]
