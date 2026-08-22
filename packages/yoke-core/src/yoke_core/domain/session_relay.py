"""Thin long-poll orchestration for one machine-relay invocation."""

from __future__ import annotations

import time
from typing import Any, Callable, Mapping

from yoke_core.domain.session_relay_expiry import settle_expired_relay_leases
from yoke_core.domain.session_relay_jobs import (
    claim_launch_job,
    claim_wake_job,
    report_launch_job,
    report_wake_job,
)
from yoke_core.domain.session_relay_policy import effective_relay_policy
from yoke_core.domain.session_relay_storage import (
    heartbeat_relay,
    machine_is_idle,
    relay_has_live_lease,
    utc_now,
    validate_heartbeat,
)
from yoke_core.domain.session_message_delivery import expire_due_recipients
from yoke_core.domain.session_message_types import parse_timestamp
from yoke_core.domain.session_relay_types import (
    MAX_RELAY_LONG_POLL_SECONDS,
    RELAY_LONG_POLL_STEP_SECONDS,
    RelayClaimOutcome,
    RelayHeartbeat,
    SessionRelayError,
)


def claim_relay_job(
    conn: Any,
    heartbeat: RelayHeartbeat,
    *,
    wait_seconds: int = MAX_RELAY_LONG_POLL_SECONDS,
    now_provider: Callable[[], str] = utc_now,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> RelayClaimOutcome:
    """Heartbeat, long-poll, lease at most one job, and return server cadence."""
    heartbeat = validate_heartbeat(heartbeat)
    wait_seconds = max(0, min(int(wait_seconds), MAX_RELAY_LONG_POLL_SECONDS))
    policy = effective_relay_policy(conn, heartbeat.project_ids)
    current = now_provider()
    heartbeat_relay(
        conn,
        heartbeat,
        state="active",
        next_poll_seconds=policy.poll_seconds,
        now=current,
    )
    settle_expired_relay_leases(conn, now=current)
    expire_due_recipients(conn, now=parse_timestamp(current))
    conn.commit()

    if relay_has_live_lease(conn, relay_id=heartbeat.relay_id, now=current):
        connected = heartbeat_relay(
            conn,
            heartbeat,
            state="active",
            next_poll_seconds=policy.poll_seconds,
            now=current,
        )
        return RelayClaimOutcome(
            relay_id=heartbeat.relay_id,
            machine_id=heartbeat.machine_id,
            state="active",
            connected_until=connected,
            next_poll_seconds=policy.poll_seconds,
        )

    started = monotonic()
    while True:
        current = now_provider()
        job = claim_launch_job(conn, heartbeat, now=current)
        if job is None:
            job = claim_wake_job(
                conn,
                heartbeat,
                now=current,
            )
        if job is not None:
            connected = heartbeat_relay(
                conn,
                heartbeat,
                state="active",
                next_poll_seconds=policy.poll_seconds,
                now=current,
            )
            return RelayClaimOutcome(
                relay_id=heartbeat.relay_id,
                machine_id=heartbeat.machine_id,
                state="active",
                connected_until=connected,
                next_poll_seconds=policy.poll_seconds,
                job=job,
            )
        # Never hold a read transaction open across the long-poll sleep.
        conn.commit()
        elapsed = monotonic() - started
        if elapsed >= wait_seconds:
            break
        sleep(min(RELAY_LONG_POLL_STEP_SECONDS, wait_seconds - elapsed))

    idle = machine_is_idle(
        conn,
        machine_id=heartbeat.machine_id,
        idle_after_minutes=policy.idle_after_minutes,
        now=current,
    )
    state = "idle" if idle else "active"
    next_poll = policy.idle_poll_seconds if idle else policy.poll_seconds
    connected = heartbeat_relay(
        conn,
        heartbeat,
        state=state,
        next_poll_seconds=next_poll,
        now=current,
    )
    return RelayClaimOutcome(
        relay_id=heartbeat.relay_id,
        machine_id=heartbeat.machine_id,
        state=state,
        connected_until=connected,
        next_poll_seconds=next_poll,
    )


def report_relay_job(
    conn: Any,
    *,
    actor_id: int,
    relay_id: str,
    job_kind: str,
    job_id: str,
    lease_id: str,
    result_code: str,
    native_session_id: str | None = None,
    adapter_revision: str | None = None,
    evidence: Mapping[str, Any] | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    """Persist one bounded native result without logging job payloads."""
    from yoke_core.domain.session_relay_storage import require_relay_actor

    require_relay_actor(conn, relay_id=relay_id, actor_id=actor_id)
    current = now or utc_now()
    if job_kind == "launch":
        return report_launch_job(
            conn,
            relay_id=relay_id,
            launch_id=job_id,
            lease_id=lease_id,
            result_code=result_code,
            native_session_id=native_session_id,
            adapter_revision=adapter_revision,
            evidence=evidence,
            now=current,
        )
    if job_kind == "wake":
        if native_session_id:
            raise SessionRelayError(
                "native_id_forbidden", "wake reports never carry a native session id"
            )
        return report_wake_job(
            conn,
            relay_id=relay_id,
            attempt_id=job_id,
            lease_id=lease_id,
            result_code=result_code,
            adapter_revision=adapter_revision,
            evidence=evidence,
            now=current,
        )
    raise SessionRelayError("job_kind_invalid", "relay job kind must be launch or wake")


__all__ = ["claim_relay_job", "report_relay_job"]
