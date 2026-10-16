"""Read native job ownership and deadlines from each job's durable owner."""

from datetime import timedelta
from typing import Any

from yoke_contracts.timestamps import parse_instant
from yoke_core.domain.session_launch_types import LAUNCH_LEASE_SECONDS
from yoke_core.domain.session_relay_storage import marker
from yoke_core.domain.session_relay_types import SessionRelayError, WAKE_LEASE_SECONDS


def require_job_lease(
    conn: Any, *, relay_id: str, job_kind: str, job_id: str, now
) -> None:
    """A newer independent claim neither extends nor invalidates this lease."""
    p = marker(conn)
    if job_kind == "launch":
        row = conn.execute(
            "SELECT a.machine_id,a.started_at,l.deadline_at "
            "FROM session_launch_attempts a JOIN session_launches l "
            "ON l.launch_id=a.launch_id "
            f"WHERE a.launch_id={p} AND a.relay_id={p} "
            "AND a.completed_at IS NULL ORDER BY a.started_at DESC LIMIT 1",
            (job_id, relay_id),
        ).fetchone()
    elif job_kind == "wake":
        row = conn.execute(
            "SELECT hs.machine_id,a.started_at FROM session_message_attempts a "
            "JOIN harness_sessions hs ON hs.session_id=a.target_session_id "
            f"WHERE a.attempt_id={p}",
            (job_id,),
        ).fetchone()
    else:
        table, key = (
            ("session_evidence_fetches", "fetch_id")
            if job_kind == "evidence"
            else ("session_termination_reaps", "target_session_id")
        )
        row = conn.execute(
            f"SELECT machine_id,lease_expires_at FROM {table} WHERE {key}={p}",
            (job_id,),
        ).fetchone()
    relay = conn.execute(
        f"SELECT machine_id FROM session_relays WHERE relay_id={p}", (relay_id,)
    ).fetchone()
    if row is None or relay is None or str(row[0]) != str(relay[0]):
        raise SessionRelayError(
            "relay_lease_mismatch",
            "This relay does not own the job's machine. Recovery: report through the owning machine relay.",
        )
    deadline = parse_instant(row[1])
    if job_kind in {"launch", "wake"}:
        deadline += timedelta(
            seconds=LAUNCH_LEASE_SECONDS if job_kind == "launch" else WAKE_LEASE_SECONDS
        )
    if job_kind == "launch":
        deadline = min(deadline, parse_instant(row[2]))
    if deadline <= parse_instant(now):
        raise SessionRelayError(
            "relay_lease_expired",
            "This job's lease expired before its report. Recovery: inspect its settled outcome and native custody before retrying.",
        )
