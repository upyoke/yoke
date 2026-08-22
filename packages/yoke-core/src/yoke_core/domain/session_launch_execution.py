"""Relay leases, native outcomes, deadlines, and reconciliation for launches."""

from __future__ import annotations

import secrets
from typing import Any
from uuid import uuid4

from yoke_core.domain.session_launch_store import (
    add_seconds,
    attestation_digest,
    begin_mutation,
    bootstrap_prompt,
    canonical_json,
    get_launch,
    marker,
    next_attempt_number,
    parse_time,
    sha256_text,
    update_launch,
    utc_now,
    value,
)
from yoke_core.domain.session_launch_types import (
    LAUNCH_LEASE_SECONDS,
    LaunchAuthorization,
    LaunchClaim,
    LaunchRecord,
    SessionLaunchError,
    ensure_operator,
)


_REPORT_RESULTS = frozenset({"native_created", "not_created", "outcome_unknown"})


def _bounded_evidence(evidence: dict[str, Any] | None) -> str:
    rendered = canonical_json(evidence or {})
    if len(rendered.encode("utf-8")) <= 2048:
        return rendered
    return canonical_json({"redacted": "oversize", "sha256": sha256_text(rendered)})


def _attempt_by_lease(conn: Any, launch_id: str, lease_id: str) -> Any:
    p = marker(conn)
    row = conn.execute(
        "SELECT attempt_id, attempt_number, started_at, completed_at, "
        "native_session_id, result_code FROM session_launch_attempts "
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
) -> None:
    p = marker(conn)
    conn.execute(
        "UPDATE session_launch_attempts SET completed_at = {0}, "
        "native_session_id = {0}, result_code = {0}, adapter_revision = {0}, "
        "evidence = {0} WHERE attempt_id = {0}".format(p),
        (
            completed_at,
            native_session_id,
            result_code,
            adapter_revision,
            _bounded_evidence(evidence),
            attempt_id,
        ),
    )


def claim_assigned_launch(
    conn: Any,
    *,
    launch_id: str,
    relay_id: str,
    machine_id: str,
    now: str | None = None,
) -> LaunchClaim:
    """Lease one assigned launch and mint its single-use attestation secret."""
    current = now or utc_now()
    begin_mutation(conn)
    try:
        launch = get_launch(conn, launch_id, for_update=True)
        if launch.state != "assigned":
            raise SessionLaunchError(
                "invalid_state", f"launch is {launch.state!r}, not assigned",
            )
        if launch.assigned_relay_id != relay_id or launch.assigned_machine_id != machine_id:
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
            "(attempt_id, launch_id, relay_id, machine_id, lease_id, "
            "attempt_number, started_at) "
            f"VALUES ({', '.join(p for _ in range(7))})",
            (
                attempt_id,
                launch_id,
                relay_id,
                machine_id,
                lease_id,
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
            raise SessionLaunchError("report_conflict", "attempt already has another outcome")
        if launch.state not in {"launching", "outcome_unknown"}:
            raise SessionLaunchError(
                "invalid_state", f"launch in state {launch.state!r} cannot accept a report",
            )
        attempt_id = str(value(attempt, "attempt_id", 0))
        _complete_attempt(
            conn,
            attempt_id=attempt_id,
            completed_at=current,
            native_session_id=native_session_id,
            result_code=result_code,
            adapter_revision=adapter_revision,
            evidence=evidence,
        )
        result_evidence = _bounded_evidence(evidence)
        if result_code == "native_created":
            if parse_time(current) >= parse_time(launch.deadline_at):
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
                    awaiting_registration_at=current,
                    result_code="native_created",
                    result_evidence=result_evidence,
                )
        elif result_code == "not_created":
            result = update_launch(
                conn,
                launch_id,
                state="failed",
                completed_at=current,
                result_code="native_create_failed",
                result_evidence=result_evidence,
            )
        else:
            result = update_launch(
                conn,
                launch_id,
                state="outcome_unknown",
                result_code="outcome_unknown",
                result_evidence=result_evidence,
            )
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise


def reconcile_launch(
    conn: Any,
    *,
    launch_id: str,
    auth: LaunchAuthorization,
    observed_native_id: str | None,
    now: str | None = None,
) -> LaunchRecord:
    """Resolve possible native creation before any retry is permitted."""
    ensure_operator(auth)
    current = now or utc_now()
    begin_mutation(conn)
    try:
        launch = get_launch(conn, launch_id, for_update=True)
        if launch.state == "succeeded":
            if observed_native_id and observed_native_id != launch.native_session_id:
                raise SessionLaunchError("reconciliation_conflict", "native id conflicts")
            conn.commit()
            return launch
        if launch.state not in {"outcome_unknown", "failed"}:
            raise SessionLaunchError(
                "invalid_state", f"launch in state {launch.state!r} is not reconcilable",
            )
        if launch.native_session_id and observed_native_id not in {
            None,
            launch.native_session_id,
        }:
            raise SessionLaunchError("reconciliation_conflict", "native id conflicts")
        if observed_native_id:
            state = (
                "awaiting_registration"
                if parse_time(current) < parse_time(launch.deadline_at)
                else "failed"
            )
            result = update_launch(
                conn,
                launch_id,
                state=state,
                native_session_id=observed_native_id,
                awaiting_registration_at=current if state == "awaiting_registration" else None,
                completed_at=current if state == "failed" else None,
                result_code=(
                    "native_created_reconciled"
                    if state == "awaiting_registration"
                    else "late_native_reconciled"
                ),
            )
        else:
            result = update_launch(
                conn,
                launch_id,
                state="failed",
                native_session_id=None,
                attestation_hash=None,
                completed_at=current,
                result_code="reconciled_not_created",
            )
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise


__all__ = [
    "claim_assigned_launch",
    "reconcile_launch",
    "report_launch_attempt",
]
