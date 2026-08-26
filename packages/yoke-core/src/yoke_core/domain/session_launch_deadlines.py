"""Deadline convergence for queued and in-flight session launches."""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.session_launch_closure_evidence import (
    closure_evidence,
    open_attempt,
)
from yoke_core.domain.session_relay_evidence import merge_redacted_evidence
from yoke_core.domain.session_launch_store import (
    LAUNCH_COLUMNS,
    add_seconds,
    begin_mutation,
    marker,
    parse_time,
    row_to_launch,
    update_launch,
    utc_now,
    value,
)
from yoke_core.domain.session_launch_types import LAUNCH_LEASE_SECONDS, LaunchRecord


def _deadline_candidates(
    conn: Any,
    *,
    launch_id: str | None,
    project_id: int | None,
) -> list[LaunchRecord]:
    p = marker(conn)
    where = ["state IN ('queued','assigned','launching','awaiting_registration')"]
    params: list[Any] = []
    if launch_id is not None:
        where.append(f"launch_id = {p}")
        params.append(launch_id)
    if project_id is not None:
        where.append(f"project_id = {p}")
        params.append(project_id)
    lock = " FOR UPDATE SKIP LOCKED" if db_backend.connection_is_postgres(conn) else ""
    rows = conn.execute(
        f"SELECT {LAUNCH_COLUMNS} FROM session_launches "
        f"WHERE {' AND '.join(where)} ORDER BY deadline_at, launch_id{lock}",
        tuple(params),
    ).fetchall()
    return [row_to_launch(row) for row in rows]


_LAUNCH_LEASE_EXPIRED_CODE = "launch_lease_expired"


def _expire_launching(
    conn: Any,
    launch: LaunchRecord,
    *,
    attempt: Any,
    now: str,
) -> LaunchRecord:
    """Mark a silent launch uncertain while saying what was observed.

    The attempt stays open on purpose: the relay may still be alive and a
    late report is the only thing that can settle a native outcome this pass
    cannot see. What changes is that the attempt no longer waits with an
    empty evidence column — the phase the launch reached and the transport
    state at expiry are written now, while they are still true, and a later
    report replaces them with the native facts it carries.
    """
    evidence = closure_evidence(
        conn,
        launch=launch,
        result_code=_LAUNCH_LEASE_EXPIRED_CODE,
        closure_reason="launch_lease_expiry",
        relay_id=value(attempt, "relay_id", 1) if attempt else launch.assigned_relay_id,
        machine_id=(
            value(attempt, "machine_id", 2) if attempt else launch.assigned_machine_id
        ),
        started_at=value(attempt, "started_at", 3) if attempt else launch.launching_at,
        now=now,
    )
    # Merge rather than replace: a relay that reported its spawn phase before
    # going quiet left the most diagnosable fact on this row, and an expiry
    # that overwrote it would destroy exactly what the closure exists to
    # preserve. The closure's own terminal code wins where the two overlap.
    rendered = merge_redacted_evidence(
        value(attempt, "evidence", 4) if attempt else None, evidence
    )
    if attempt is not None:
        p = marker(conn)
        conn.execute(
            f"UPDATE session_launch_attempts SET evidence = {p} "
            f"WHERE attempt_id = {p} AND completed_at IS NULL",
            (rendered, str(value(attempt, "attempt_id", 0))),
        )
    return update_launch(
        conn,
        launch.launch_id,
        delivery_changed_at=now,
        state="outcome_unknown",
        result_code=_LAUNCH_LEASE_EXPIRED_CODE,
        result_evidence=rendered,
    )


def _expire_at_deadline(
    conn: Any,
    launch: LaunchRecord,
    *,
    now: str,
) -> LaunchRecord:
    """Close a launch at its deadline, saying what the server last observed.

    A launch that reached ``awaiting_registration`` and then ran out of time
    is the shape an operator has to diagnose most often, and it used to land
    with a bare terminal code: no phase, no relay, no transport state, nothing
    to separate "the native never came up" from "the native came up and could
    not bind". The same facts the lease-expiry closure records are true here
    and are written while they still are.
    """
    registration = launch.state == "awaiting_registration"
    result_code = "registration_deadline" if registration else "launch_deadline"
    evidence = closure_evidence(
        conn,
        launch=launch,
        result_code=result_code,
        closure_reason="deadline_expiry",
        relay_id=launch.assigned_relay_id,
        machine_id=launch.assigned_machine_id,
        started_at=launch.awaiting_registration_at or launch.launching_at,
        now=now,
    )
    return update_launch(
        conn,
        launch.launch_id,
        state="failed" if registration else "expired",
        completed_at=now,
        result_code=result_code,
        result_evidence=merge_redacted_evidence(launch.result_evidence, evidence),
    )


def settle_launch_deadlines(
    conn: Any,
    *,
    now: str | None = None,
    launch_id: str | None = None,
    project_id: int | None = None,
) -> list[LaunchRecord]:
    """Close expired queues and surface uncertain expired native attempts."""
    current = now or utc_now()
    begin_mutation(conn)
    changed: list[LaunchRecord] = []
    try:
        for launch in _deadline_candidates(
            conn,
            launch_id=launch_id,
            project_id=project_id,
        ):
            deadline_passed = parse_time(current) >= parse_time(launch.deadline_at)
            if launch.state == "launching":
                row = open_attempt(conn, launch.launch_id)
                lease_passed = bool(row) and parse_time(current) >= parse_time(
                    add_seconds(str(value(row, "started_at", 3)), LAUNCH_LEASE_SECONDS)
                )
                if deadline_passed or lease_passed:
                    changed.append(
                        _expire_launching(conn, launch, attempt=row, now=current)
                    )
            elif deadline_passed:
                changed.append(_expire_at_deadline(conn, launch, now=current))
        conn.commit()
        return changed
    except Exception:
        conn.rollback()
        raise


__all__ = ["settle_launch_deadlines"]
