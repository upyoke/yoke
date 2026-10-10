"""Lease and settle best-effort native reaping for terminated sessions."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from yoke_contracts.timestamps import parse_instant
from yoke_core.domain.db_helpers import instant_parameter
from typing import Any, Mapping
from uuid import uuid4

from yoke_contracts.session_control.liveness import LIVENESS_ENDED
from yoke_core.domain.session_message_types import (
    parse_timestamp,
    row_dict,
)
from yoke_core.domain.session_relay_evidence import redacted_evidence
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
    WAKE_LEASE_SECONDS,
)


TERMINATION_REAP_RESULT_CODES = frozenset(
    {
        "terminated",
        "killed",
        "already_exited",
        "not_found",
        "shared_process_group",
        "outcome_unknown",
        "failed",
    }
)
_SUCCESS_RESULTS = frozenset({"terminated", "killed", "already_exited"})


def release_expired_termination_leases(conn: Any, *, now: datetime | str) -> int:
    cursor = conn.execute(
        "UPDATE session_termination_reaps SET state='pending',lease_id=NULL,"
        "lease_expires_at=NULL WHERE state='leased' AND lease_expires_at<="
        + marker(conn),
        (instant_parameter(conn, parse_instant(now)),),
    )
    return max(0, int(cursor.rowcount or 0))


def claim_termination_reap(
    conn: Any,
    heartbeat: RelayHeartbeat,
    *,
    now: datetime | str,
) -> RelayJob | None:
    projects = tuple(sorted({int(value) for value in heartbeat.project_ids}))
    if not projects:
        return None
    p = marker(conn)
    lock = " FOR UPDATE SKIP LOCKED" if p == "%s" else ""
    row = conn.execute(
        "SELECT * FROM session_termination_reaps WHERE state='pending' "
        f"AND machine_id={p} AND project_id IN ("
        + ",".join(p for _ in projects)
        + ") ORDER BY requested_at,target_session_id LIMIT 1"
        + lock,
        (heartbeat.machine_id, *projects),
    ).fetchone()
    if row is None:
        return None
    selected = row_dict(row)
    lease_id = str(uuid4())
    current = parse_timestamp(now)
    if current is None:
        raise SessionRelayError(
            "clock_invalid", "relay termination lease time is invalid"
        )
    expires_at = current + timedelta(seconds=WAKE_LEASE_SECONDS)
    cursor = conn.execute(
        "UPDATE session_termination_reaps SET state='leased',lease_id="
        + p
        + ",lease_expires_at="
        + p
        + f" WHERE target_session_id={p} AND state='pending'",
        (
            lease_id,
            instant_parameter(conn, parse_instant(expires_at)),
            str(selected["target_session_id"]),
        ),
    )
    if cursor.rowcount != 1:
        return None
    mark_relay_batch(
        conn,
        relay_id=heartbeat.relay_id,
        batch_id=lease_id,
        expires_at=expires_at,
        now=now,
    )
    conn.commit()
    surface = str(selected.get("executor_surface") or "")
    return RelayJob(
        job_kind="terminate",
        job_id=str(selected["target_session_id"]),
        lease_id=lease_id,
        machine_id=heartbeat.machine_id,
        surface=surface,
        surface_version=str(heartbeat.surface_versions.get(surface) or ""),
        project_id=int(selected["project_id"]),
        native_instruction="",
        target_session_id=str(selected["target_session_id"]),
        target_native_thread_id=(
            str(selected["target_native_thread_id"])
            if selected.get("target_native_thread_id")
            else None
        ),
        target_launch_id=(
            str(selected["launch_id"]) if selected.get("launch_id") else None
        ),
        # The kill already landed, so the target's derived liveness is ended.
        # There is no `terminated` liveness value; the kill is its cause.
        target_liveness=LIVENESS_ENDED,
    )


def report_termination_reap(
    conn: Any,
    *,
    relay_id: str,
    target_session_id: str,
    lease_id: str,
    result_code: str,
    adapter_revision: str | None,
    evidence: Mapping[str, Any] | None,
    now: datetime | str,
) -> dict[str, Any]:
    if result_code not in TERMINATION_REAP_RESULT_CODES:
        raise SessionRelayError("result_invalid", "unknown termination result code")
    p = marker(conn)
    row = conn.execute(
        "SELECT state,lease_id,result_code,evidence FROM session_termination_reaps "
        f"WHERE target_session_id={p}",
        (target_session_id,),
    ).fetchone()
    if row is None:
        raise SessionRelayError("attempt_missing", "termination reap does not exist")
    if str(row[1] or "") != lease_id:
        raise SessionRelayError(
            "lease_mismatch", "termination reap lease does not match"
        )
    if str(row[0]) in {"succeeded", "failed"}:
        if str(row[2] or "") == result_code:
            return {"target_session_id": target_session_id, "result_code": result_code}
        raise SessionRelayError(
            "report_conflict", "termination reap was already reported"
        )
    require_relay_batch(conn, relay_id=relay_id, now=now)
    state = "succeeded" if result_code in _SUCCESS_RESULTS else "failed"
    attempts = json.loads(row[3] or "{}").get("attempts", [])
    conn.execute(
        "UPDATE session_termination_reaps SET state="
        + p
        + ",completed_at="
        + p
        + ",result_code="
        + p
        + ",evidence="
        + p
        + f" WHERE target_session_id={p}",
        (
            state,
            instant_parameter(conn, parse_instant(now)),
            result_code,
            json.dumps(
                {
                    **json.loads(
                        redacted_evidence(
                            {
                                **dict(evidence or {}),
                                "adapter_revision": adapter_revision,
                            }
                        )
                    ),
                    **({"attempts": attempts} if attempts else {}),
                }
            ),
            target_session_id,
        ),
    )
    clear_relay_batch_when_drained(conn, relay_id=relay_id, batch_id=lease_id)
    conn.commit()
    return {"target_session_id": target_session_id, "result_code": result_code}


__all__ = [
    "TERMINATION_REAP_RESULT_CODES",
    "claim_termination_reap",
    "release_expired_termination_leases",
    "report_termination_reap",
]
