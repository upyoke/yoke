"""Operator reconciliation of uncertain native launch outcomes."""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.session_launch_closure_evidence import closure_evidence
from yoke_core.domain.session_launch_native_progress import (
    native_attempt_pending,
    native_attempt_refusal,
)
from yoke_core.domain.session_launch_registered_session_binding import (
    bind_existing_registered_session,
)
from yoke_core.domain.session_launch_store import (
    begin_mutation,
    canonical_json,
    get_launch,
    marker,
    parse_time,
    update_launch,
    utc_now,
)
from yoke_core.domain.session_launch_types import (
    LaunchAuthorization,
    LaunchRecord,
    SessionLaunchError,
    ensure_operator,
)
from yoke_core.domain.session_relay_storage import (
    clear_relay_batch_when_drained,
    relay_holds_batch,
)


def _lock(conn: Any) -> str:
    return " FOR UPDATE" if db_backend.connection_is_postgres(conn) else ""


def _settle_open_attempts(
    conn: Any,
    *,
    launch: LaunchRecord,
    observed_native_id: str | None,
    now: str,
) -> None:
    launch_id = launch.launch_id
    p = marker(conn)
    attempts = conn.execute(
        "SELECT attempt_id,relay_id,batch_id,machine_id,started_at "
        f"FROM session_launch_attempts "
        f"WHERE launch_id={p} AND completed_at IS NULL ORDER BY attempt_number"
        + _lock(conn),
        (launch_id,),
    ).fetchall()
    if observed_native_id and len(attempts) > 1:
        raise SessionLaunchError(
            "reconciliation_attempt_ambiguous",
            "one observed native id cannot resolve multiple open launch attempts",
        )
    for attempt in attempts:
        relay_id = str(attempt[1] or "")
        if not relay_id:
            continue
        # Only the batch that leased this attempt can still be executing it.
        # A relay that has moved on to a newer batch has abandoned this one,
        # which is exactly the attempt an operator is here to repair.
        if relay_holds_batch(
            conn,
            relay_id=relay_id,
            batch_id=str(attempt[2] or ""),
            now=now,
        ):
            raise SessionLaunchError(
                "relay_lease_active",
                "launch attempt is still held by an active relay batch",
            )

    result_code = "native_created" if observed_native_id else "not_created"
    evidence_code = (
        "reconciled_native_created" if observed_native_id else "reconciled_not_created"
    )
    for attempt in attempts:
        conn.execute(
            "UPDATE session_launch_attempts SET completed_at="
            + p
            + ",native_session_id="
            + p
            + ",result_code="
            + p
            + ",adapter_revision=NULL,evidence="
            + p
            + f" WHERE attempt_id={p} AND completed_at IS NULL",
            (
                now,
                observed_native_id,
                result_code,
                canonical_json(
                    closure_evidence(
                        conn,
                        launch=launch,
                        result_code=evidence_code,
                        closure_reason="operator_reconciliation",
                        relay_id=attempt[1],
                        machine_id=attempt[3],
                        started_at=attempt[4],
                        now=now,
                    )
                ),
                str(attempt[0]),
            ),
        )
        relay_id = str(attempt[1] or "")
        if relay_id:
            clear_relay_batch_when_drained(
                conn,
                relay_id=relay_id,
                batch_id=str(attempt[2] or ""),
            )


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
        if native_attempt_pending(conn, launch, now=current):
            raise SessionLaunchError(
                "native_process_alive", native_attempt_refusal(launch)
            )
        if launch.state == "succeeded":
            if observed_native_id and observed_native_id != launch.native_session_id:
                raise SessionLaunchError(
                    "reconciliation_conflict", "native id conflicts"
                )
            conn.commit()
            return launch
        if launch.state not in {"outcome_unknown", "failed"}:
            raise SessionLaunchError(
                "invalid_state",
                f"launch in state {launch.state!r} is not reconcilable",
            )
        if launch.native_session_id and observed_native_id not in {
            None,
            launch.native_session_id,
        }:
            raise SessionLaunchError("reconciliation_conflict", "native id conflicts")

        _settle_open_attempts(
            conn,
            launch=launch,
            observed_native_id=observed_native_id,
            now=current,
        )
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
                awaiting_registration_at=current
                if state == "awaiting_registration"
                else None,
                completed_at=current if state == "failed" else None,
                result_code=(
                    "native_created_reconciled"
                    if state == "awaiting_registration"
                    else "late_native_reconciled"
                ),
            )
        elif (
            launch.state == "failed"
            and launch.result_code == "reconciled_not_created"
            and launch.native_session_id is None
        ):
            result = launch
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
        result = bind_existing_registered_session(conn, launch=result, now=current)
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise


__all__ = ["reconcile_launch"]
