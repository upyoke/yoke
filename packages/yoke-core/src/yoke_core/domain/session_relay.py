"""Thin long-poll orchestration for one machine-relay invocation."""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Mapping

from yoke_contracts.session_control.surface_versions import (
    surface_operation_supported,
)
from yoke_core.domain.session_evidence_fetch import (
    expire_stale_evidence_requests,
)
from yoke_core.domain.session_evidence_relay_job import (
    claim_evidence_fetch,
    report_evidence_fetch,
)
from yoke_core.domain.session_relay_expiry import settle_expired_relay_leases
from yoke_core.domain.session_relay_jobs import (
    claim_wake_job,
    report_launch_job,
    report_wake_job,
)
from yoke_core.domain.session_relay_launch_batch import claim_launch_batch
from yoke_core.domain.session_relay_policy import effective_relay_policy
from yoke_core.domain.session_relay_storage import (
    heartbeat_relay,
    machine_is_idle,
    relay_has_live_batch,
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
from yoke_core.domain.session_termination_reap import (
    claim_termination_reap,
    release_expired_termination_leases,
    report_termination_reap,
)


_LOG = logging.getLogger(__name__)


def claim_relay_job(
    conn: Any,
    heartbeat: RelayHeartbeat,
    *,
    wait_seconds: int = MAX_RELAY_LONG_POLL_SECONDS,
    broker_only: bool = False,
    broker_lease_id: str | None = None,
    broker_session_id: str | None = None,
    now_provider: Callable[[], str] = utc_now,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> RelayClaimOutcome:
    """Heartbeat, long-poll, lease one batch of work, and return server cadence.

    Launches are independent native creates, so a poll leases up to the
    organization's batch cap of them together. Wakes touch shared session
    state, so a poll leases at most one.
    """
    heartbeat = validate_heartbeat(heartbeat)
    if broker_only != bool(broker_lease_id):
        raise SessionRelayError(
            "broker_lease_required",
            "broker-only claims require one exact broker lease",
        )
    if broker_only and not str(broker_session_id or "").strip():
        raise SessionRelayError(
            "broker_session_required",
            "broker-only claims require a verified broker session",
        )
    wait_seconds = (
        0
        if broker_only
        else max(0, min(int(wait_seconds), MAX_RELAY_LONG_POLL_SECONDS))
    )
    policy = effective_relay_policy(conn, heartbeat.project_ids)
    current = now_provider()
    heartbeat_relay(
        conn,
        heartbeat,
        state="active",
        next_poll_seconds=policy.poll_seconds,
        now=current,
    )
    from yoke_core.domain.session_wake_reconciliation import (
        reconcile_spawned_wake_attempts,
    )

    reconcile_spawned_wake_attempts(conn, now=current)
    release_expired_termination_leases(conn, now=current)
    expire_stale_evidence_requests(conn, now=current)
    settle_expired_relay_leases(conn, now=current)
    expire_due_recipients(conn, now=parse_timestamp(current))
    conn.commit()

    if not broker_only:
        from yoke_core.domain.merge_queue_landing_observer import (
            observe_pending_landings,
        )

        try:
            observe_pending_landings(
                conn,
                heartbeat.project_ids,
                now=parse_timestamp(current),
            )
        except Exception as exc:  # noqa: BLE001 - relay work remains available
            conn.rollback()
            _LOG.warning("merge-queue landing observation skipped: %s", exc)

    if relay_has_live_batch(conn, relay_id=heartbeat.relay_id, now=current):
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
            launch_stagger_seconds=policy.launch_stagger_seconds,
        )

    started = monotonic()
    while True:
        current = now_provider()
        termination = (
            None
            if broker_only
            else claim_termination_reap(conn, heartbeat, now=current)
        )
        jobs: tuple[Any, ...] = (termination,) if termination is not None else ()
        if not jobs and not broker_only:
            # A seat's dispatch is blocked on this read and it costs the
            # machine one file tail, so it goes ahead of the minutes-long
            # native work rather than behind it.
            evidence = claim_evidence_fetch(conn, heartbeat, now=current)
            jobs = (evidence,) if evidence is not None else ()
        if not jobs:
            jobs = (
                ()
                if broker_only
                else tuple(
                    claim_launch_batch(
                        conn,
                        heartbeat,
                        now=current,
                        cap=policy.launch_batch,
                    )
                )
            )
        if not jobs:
            wake = claim_wake_job(
                conn,
                heartbeat,
                now=current,
                broker_only=broker_only,
                broker_lease_id=broker_lease_id,
                broker_session_id=broker_session_id,
            )
            jobs = (wake,) if wake is not None else ()
        if jobs:
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
                launch_stagger_seconds=policy.launch_stagger_seconds,
                jobs=jobs,
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
    launch_capable = any(
        surface_operation_supported(surface, version, "create")
        for surface, version in heartbeat.surface_versions.items()
    )
    next_poll = (
        policy.idle_poll_seconds if idle and not launch_capable else policy.poll_seconds
    )
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
        launch_stagger_seconds=policy.launch_stagger_seconds,
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
    document: Mapping[str, Any] | None = None,
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
    if job_kind == "evidence":
        if native_session_id:
            raise SessionRelayError(
                "native_id_forbidden",
                "evidence reports never carry a native session id",
            )
        return report_evidence_fetch(
            conn,
            relay_id=relay_id,
            fetch_id=job_id,
            lease_id=lease_id,
            result_code=result_code,
            document=document,
            now=current,
        )
    if job_kind == "terminate":
        if native_session_id:
            raise SessionRelayError(
                "native_id_forbidden",
                "termination reports never carry a native session id",
            )
        return report_termination_reap(
            conn,
            relay_id=relay_id,
            target_session_id=job_id,
            lease_id=lease_id,
            result_code=result_code,
            adapter_revision=adapter_revision,
            evidence=evidence,
            now=current,
        )
    raise SessionRelayError(
        "job_kind_invalid",
        "relay job kind must be launch, wake, terminate, or evidence",
    )


__all__ = ["claim_relay_job", "report_relay_job"]
