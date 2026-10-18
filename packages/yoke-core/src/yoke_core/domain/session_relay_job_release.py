"""Release unstarted relay jobs without spending their execution deadlines."""

from typing import Any

from yoke_contracts.timestamps import parse_instant
from yoke_core.domain.db_helpers import instant_parameter
from yoke_core.domain.session_launch_store import (
    begin_mutation,
    get_launch,
    update_launch,
)
from yoke_core.domain.session_relay_evidence import merge_redacted_evidence
from yoke_core.domain.session_relay_job_leases import require_job_lease
from yoke_core.domain.session_relay_storage import (
    clear_relay_batch_when_drained,
    marker,
)
from yoke_core.domain.session_relay_types import SessionRelayError


def _refuse():
    raise SessionRelayError(
        "relay_release_conflict",
        "The job is no longer an unstarted lease owned by this relay. "
        "Recovery: inspect its current attempt and native custody before retrying.",
    )


def release_relay_job(
    conn: Any,
    *,
    relay_id,
    job_kind,
    job_id,
    lease_id,
    native_session_id,
    evidence,
    now,
):
    """Atomically settle the exact lease and make its durable owner claimable."""
    if native_session_id:
        _refuse()
    p = marker(conn)
    current = instant_parameter(conn, parse_instant(now))
    lock = " FOR UPDATE" if p == "%s" else ""
    begin_mutation(conn)
    try:
        if job_kind != "launch":
            if job_kind == "wake":
                owner_sql = (
                    "SELECT hs.machine_id FROM session_message_attempts a "
                    "JOIN harness_sessions hs ON hs.session_id=a.target_session_id "
                    f"WHERE a.attempt_id={p} AND a.lease_id={p}"
                )
            elif job_kind in {"terminate", "evidence"}:
                table, key = (
                    ("session_termination_reaps", "target_session_id")
                    if job_kind == "terminate"
                    else ("session_evidence_fetches", "fetch_id")
                )
                owner_sql = (
                    f"SELECT machine_id FROM {table} WHERE {key}={p} AND lease_id={p}"
                )
            else:
                _refuse()
            owner = conn.execute(owner_sql, (job_id, lease_id)).fetchone()
            relay = conn.execute(
                f"SELECT machine_id FROM session_relays WHERE relay_id={p}", (relay_id,)
            ).fetchone()
            if owner is None or relay is None or str(owner[0]) != str(relay[0]):
                _refuse()
        if job_kind == "launch":
            launch = get_launch(conn, job_id, for_update=True)
            row = conn.execute(
                "SELECT attempt_id,completed_at,result_code,evidence,batch_id "
                f"FROM session_launch_attempts WHERE launch_id={p} "
                f"AND lease_id={p} AND relay_id={p}",
                (job_id, lease_id, relay_id),
            ).fetchone()
            if row is None:
                _refuse()
            if row[1] is not None:
                if row[2] != "released":
                    _refuse()
            else:
                if (
                    launch.state != "launching"
                    or launch.native_session_id
                    or launch.registered_session_id
                ):
                    _refuse()
                # A progress report means admission already handed the job to an adapter.
                if merge_redacted_evidence(row[3], None) != "{}":
                    _refuse()
                require_job_lease(
                    conn, relay_id=relay_id, job_kind=job_kind, job_id=job_id, now=now
                )
                stored = merge_redacted_evidence(row[3], evidence)
                conn.execute(
                    f"UPDATE session_launch_attempts SET completed_at={p},"
                    f"result_code='released',evidence={p} WHERE attempt_id={p}",
                    (current, stored, row[0]),
                )
                update_launch(
                    conn,
                    job_id,
                    state="assigned",
                    launching_at=None,
                    attestation_hash=None,
                    attestation_consumed_at=None,
                    result_code="released",
                    result_evidence=stored,
                )
            clear_relay_batch_when_drained(
                conn, relay_id=relay_id, batch_id=str(row[4] or "")
            )
        elif job_kind == "wake":
            row = conn.execute(
                "SELECT completed_at,result_code,message_id,target_session_id,evidence "
                f"FROM session_message_attempts WHERE attempt_id={p} AND lease_id={p} "
                "AND attempt_kind='wake_relay'" + lock,
                (job_id, lease_id),
            ).fetchone()
            if row is None:
                _refuse()
            if row[0] is not None:
                if row[1] != "released":
                    _refuse()
            else:
                if row[1]:
                    _refuse()
                require_job_lease(
                    conn, relay_id=relay_id, job_kind=job_kind, job_id=job_id, now=now
                )
                conn.execute(
                    f"UPDATE session_message_attempts SET completed_at={p},result_code='released',"
                    f"evidence={p} WHERE attempt_id={p}",
                    (current, merge_redacted_evidence(row[4], evidence), job_id),
                )
                conn.execute(
                    "UPDATE session_message_recipients SET wake_attempt_count="
                    "CASE WHEN wake_attempt_count>0 THEN wake_attempt_count-1 ELSE 0 END,"
                    f"wake_after={p} WHERE message_id={p} AND session_id={p} AND state='pending'",
                    (current, row[2], row[3]),
                )
        elif job_kind in {"terminate", "evidence"}:
            table, key = (
                ("session_termination_reaps", "target_session_id")
                if job_kind == "terminate"
                else ("session_evidence_fetches", "fetch_id")
            )
            row = conn.execute(
                f"SELECT state,result_code FROM {table} WHERE {key}={p} AND lease_id={p}"
                + lock,
                (job_id, lease_id),
            ).fetchone()
            if row is None:
                _refuse()
            if row[0] == "pending" and row[1] == "released":
                pass
            elif row[0] == "leased":
                require_job_lease(
                    conn, relay_id=relay_id, job_kind=job_kind, job_id=job_id, now=now
                )
                conn.execute(
                    f"UPDATE {table} SET state='pending',result_code='released' "
                    f"WHERE {key}={p} AND lease_id={p}",
                    (job_id, lease_id),
                )
            else:
                _refuse()
        else:
            raise SessionRelayError(
                "job_kind_invalid", "Unknown relay job kind; inspect the claimed job."
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return {"job_id": job_id, "result_code": "released"}
