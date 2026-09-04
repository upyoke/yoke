"""Relay leases, native outcomes, deadlines, and reconciliation for launches."""

from __future__ import annotations

import secrets
from typing import Any
from uuid import uuid4

from yoke_core.domain.session_launch_closure_evidence import closure_evidence
from yoke_core.domain.session_launch_native_progress import native_launch_updates
from yoke_core.domain.session_launch_registered_session_binding import (
    bind_existing_registered_session,
)
from yoke_core.domain.session_launch_visibility import launch_execution_failure_code
from yoke_core.domain.session_launch_store import (
    add_seconds,
    attestation_digest,
    begin_mutation,
    bootstrap_prompt,
    get_launch,
    marker,
    next_attempt_number,
    parse_time,
    update_launch,
    utc_now,
    value,
)
from yoke_core.domain.session_launch_reconciliation import reconcile_launch
from yoke_core.domain.session_relay_evidence import (
    evidence_result_code,
    merge_redacted_evidence,
)
from yoke_core.domain.session_launch_types import (
    LAUNCH_LEASE_SECONDS,
    LaunchClaim,
    LaunchRecord,
    SessionLaunchError,
)


_REPORT_RESULTS = frozenset({"native_created", "not_created", "outcome_unknown"})
_REPORT_STATES = ("launching", "awaiting_registration", "outcome_unknown")


def _attempt_by_lease(conn: Any, launch_id: str, lease_id: str) -> Any:
    p = marker(conn)
    row = conn.execute(
        "SELECT attempt_id, attempt_number, started_at, completed_at, "
        "native_session_id, result_code, evidence FROM session_launch_attempts "
        f"WHERE launch_id = {p} AND lease_id = {p}",
        (launch_id, lease_id),
    ).fetchone()
    if row is None:
        raise SessionLaunchError("lease_invalid", "launch attempt lease was not found")
    return row


def _complete_attempt(
    conn: Any,
    *,
    attempt_id: str,
    completed_at: str,
    native_session_id: str | None,
    result_code: str,
    adapter_revision: str | None,
    evidence: dict[str, Any] | None,
    prior_evidence: Any = None,
) -> None:
    p = marker(conn)
    conn.execute(
        "UPDATE session_launch_attempts SET completed_at = {0}, "
        "native_session_id = {0}, result_code = {0}, "
        "adapter_revision = COALESCE({0}, adapter_revision), "
        "evidence = {0} WHERE attempt_id = {0}".format(p),
        (
            completed_at,
            native_session_id,
            result_code,
            adapter_revision,
            merge_redacted_evidence(prior_evidence, evidence),
            attempt_id,
        ),
    )


def expire_launch_attempt(
    conn: Any,
    *,
    launch_id: str,
    lease_id: str,
    result_code: str,
    now: str,
) -> LaunchRecord:
    """Close an abandoned relay attempt without erasing its progress evidence."""
    begin_mutation(conn)
    try:
        launch = get_launch(conn, launch_id, for_update=True)
        attempt = _attempt_by_lease(conn, launch_id, lease_id)
        completed = value(attempt, "completed_at", 3)
        if completed:
            conn.commit()
            return launch
        # Compose the observable facts here rather than inheriting whatever an
        # earlier pass happened to leave behind. The deadline pass only visits
        # a launch still in flight, so a launch cancelled out of ``launching``
        # reaches this closure with nothing written, and an attempt closed
        # with only its result code is the silent death this path exists to
        # end. Merging keeps any richer document a prior pass did write.
        evidence = closure_evidence(
            conn,
            launch=launch,
            result_code=result_code,
            closure_reason="relay_lease_expiry",
            relay_id=launch.assigned_relay_id,
            machine_id=launch.assigned_machine_id,
            started_at=value(attempt, "started_at", 2),
            now=now,
        )
        merged = merge_redacted_evidence(value(attempt, "evidence", 6), evidence)
        _complete_attempt(
            conn,
            attempt_id=str(value(attempt, "attempt_id", 0)),
            completed_at=now,
            native_session_id=None,
            result_code=result_code,
            adapter_revision=None,
            evidence=evidence,
            prior_evidence=value(attempt, "evidence", 6),
        )
        result = update_launch(
            conn,
            launch_id,
            delivery_changed_at=now,
            state="outcome_unknown",
            result_code=result_code,
            result_evidence=merged,
        )
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise


def claim_assigned_launch(
    conn: Any,
    *,
    launch_id: str,
    relay_id: str,
    machine_id: str,
    batch_id: str | None = None,
    now: str | None = None,
) -> LaunchClaim:
    """Lease one assigned launch and mint its single-use attestation secret.

    ``batch_id`` names the relay poll that leased this attempt, so a later
    reader can tell an attempt the relay still owns from one it has moved on
    from. A launch leased outside a relay poll belongs to no batch.
    """
    current = now or utc_now()
    begin_mutation(conn)
    try:
        launch = get_launch(conn, launch_id, for_update=True)
        if launch.state != "assigned":
            raise SessionLaunchError(
                "invalid_state",
                f"launch is {launch.state!r}, not assigned",
            )
        if (
            launch.assigned_relay_id != relay_id
            or launch.assigned_machine_id != machine_id
        ):
            raise SessionLaunchError("relay_mismatch", "launch is assigned elsewhere")
        if parse_time(current) >= parse_time(launch.deadline_at):
            update_launch(
                conn,
                launch_id,
                state="expired",
                completed_at=current,
                result_code="launch_deadline",
            )
            conn.commit()
            raise SessionLaunchError("expired", "launch deadline has passed")

        attempt_id = str(uuid4())
        lease_id = str(uuid4())
        attempt_number = next_attempt_number(conn, launch_id)
        attestation = secrets.token_urlsafe(32)
        p = marker(conn)
        conn.execute(
            "INSERT INTO session_launch_attempts "
            "(attempt_id, launch_id, relay_id, machine_id, lease_id, batch_id, "
            "attempt_number, started_at) "
            f"VALUES ({', '.join(p for _ in range(8))})",
            (
                attempt_id,
                launch_id,
                relay_id,
                machine_id,
                lease_id,
                batch_id,
                attempt_number,
                current,
            ),
        )
        launched = update_launch(
            conn,
            launch_id,
            state="launching",
            launching_at=current,
            attestation_hash=attestation_digest(attestation),
            attestation_consumed_at=None,
            result_code=None,
            result_evidence=None,
        )
        conn.commit()
        lease_expires = min(
            parse_time(add_seconds(current, LAUNCH_LEASE_SECONDS)),
            parse_time(launch.deadline_at),
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        return LaunchClaim(
            launch=launched,
            attempt_id=attempt_id,
            attempt_number=attempt_number,
            lease_id=lease_id,
            lease_expires_at=lease_expires,
            bootstrap_prompt=bootstrap_prompt(launch_id),
            attestation=attestation,
        )
    except Exception:
        conn.rollback()
        raise


def report_launch_attempt(
    conn: Any,
    *,
    launch_id: str,
    lease_id: str,
    result_code: str,
    native_session_id: str | None = None,
    adapter_revision: str | None = None,
    evidence: dict[str, Any] | None = None,
    now: str | None = None,
) -> LaunchRecord:
    """Persist the native-create boundary without guessing an uncertain outcome."""
    if result_code not in _REPORT_RESULTS:
        raise SessionLaunchError("result_invalid", "unknown launch attempt result")
    if result_code == "native_created" and not str(native_session_id or "").strip():
        result_code = "outcome_unknown"
    current = now or utc_now()
    begin_mutation(conn)
    try:
        launch = get_launch(conn, launch_id, for_update=True)
        attempt = _attempt_by_lease(conn, launch_id, lease_id)
        completed = value(attempt, "completed_at", 3)
        previous_code = value(attempt, "result_code", 5)
        previous_native = value(attempt, "native_session_id", 4)
        if completed:
            if previous_code == result_code and previous_native == native_session_id:
                conn.commit()
                return launch
            raise SessionLaunchError(
                "report_conflict", "attempt already has another outcome"
            )
        if launch.state not in _REPORT_STATES:
            raise SessionLaunchError(
                "invalid_state",
                f"launch in state {launch.state!r} cannot accept a report",
            )
        attempt_id = str(value(attempt, "attempt_id", 0))
        prior_evidence = value(attempt, "evidence", 6)
        _complete_attempt(
            conn,
            attempt_id=attempt_id,
            completed_at=current,
            native_session_id=native_session_id,
            result_code=result_code,
            adapter_revision=adapter_revision,
            evidence=evidence,
            prior_evidence=prior_evidence,
        )
        result_evidence = merge_redacted_evidence(prior_evidence, evidence)
        evidence_code = evidence_result_code(evidence)
        telemetry = native_launch_updates(evidence, observed_at=current)
        if telemetry:
            launch = update_launch(conn, launch_id, **telemetry)
        if result_code == "native_created":
            if launch.state == "outcome_unknown":
                result = update_launch(
                    conn,
                    launch_id,
                    delivery_changed_at=current,
                    state="outcome_unknown",
                    native_session_id=native_session_id,
                    result_code="late_native_requires_reconciliation",
                    result_evidence=result_evidence,
                )
            elif parse_time(current) >= parse_time(launch.deadline_at):
                result = update_launch(
                    conn,
                    launch_id,
                    state="failed",
                    native_session_id=native_session_id,
                    completed_at=current,
                    result_code="late_native_result",
                    result_evidence=result_evidence,
                )
            else:
                result = update_launch(
                    conn,
                    launch_id,
                    state="awaiting_registration",
                    native_session_id=native_session_id,
                    awaiting_registration_at=launch.awaiting_registration_at or current,
                    result_code="native_created",
                    result_evidence=result_evidence,
                )
        elif result_code == "not_created":
            result = update_launch(
                conn,
                launch_id,
                state="failed",
                completed_at=current,
                result_code=launch_execution_failure_code(evidence_code),
                result_evidence=result_evidence,
            )
        else:
            result = update_launch(
                conn,
                launch_id,
                delivery_changed_at=current,
                state="outcome_unknown",
                result_code=evidence_code or "outcome_unknown",
                result_evidence=result_evidence,
            )
        result = bind_existing_registered_session(conn, launch=result, now=current)
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise


__all__ = [
    "claim_assigned_launch",
    "expire_launch_attempt",
    "reconcile_launch",
    "report_launch_attempt",
]
