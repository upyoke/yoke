"""Deadline convergence for queued and in-flight session launches.

A launch's ``deadline_at`` is a spawn window, and the window starts when a
relay picks the launch up — not when it was created. One machine drains its
queue one native create at a time, so a launch created in a burst can wait
many minutes behind its siblings; charging that wait against its window
expired healthy launches before they ever ran. While a launch waits for
pickup its window does not run. The queue is bounded instead by its relay
staying connected, and by ``LAUNCH_QUEUE_WAIT_SECONDS`` for a relay that stays
connected yet never takes it.
"""

from __future__ import annotations

from yoke_core.domain.db_helpers import instant_parameter

from yoke_contracts.timestamps import parse_instant

from datetime import datetime

from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.session_launch_closure_evidence import (
    TRANSPORT_RELAY_CONNECTED,
    closure_evidence,
    open_attempt,
    relay_transport_state,
)
from yoke_core.domain.session_launch_native_progress import native_attempt_pending
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
from yoke_core.domain.session_launch_types import (
    LAUNCH_LEASE_SECONDS,
    MAX_LAUNCH_DEADLINE_SECONDS,
    LaunchRecord,
    SessionLaunchError,
)
from .session_launch_delivery_state import (
    IN_FLIGHT_LAUNCH_STATES,
    QUEUED_LAUNCH_STATES,
)


def _deadline_candidates(
    conn: Any,
    *,
    launch_id: str | None,
    project_id: int | None,
) -> list[LaunchRecord]:
    p = marker(conn)
    states = sorted(IN_FLIGHT_LAUNCH_STATES)
    where = [f"state IN ({', '.join(p for _ in states)})"]
    params: list[Any] = list(states)
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
LAUNCH_QUEUE_WAIT_SECONDS = MAX_LAUNCH_DEADLINE_SECONDS
_QUEUE_WAIT_EXPIRY = "queue_wait_expiry"


def _queued_since(launch: LaunchRecord) -> datetime:
    return launch.assigned_at or launch.created_at


def queue_wait_exhausted(
    conn: Any, launch: LaunchRecord, *, now: datetime | str
) -> str | None:
    """Name why a launch still waiting for pickup must close, else ``None``."""
    current = parse_time(now)
    if current >= parse_time(
        add_seconds(_queued_since(launch), LAUNCH_QUEUE_WAIT_SECONDS)
    ):
        return _QUEUE_WAIT_EXPIRY
    if current >= parse_time(launch.deadline_at) and (
        relay_transport_state(conn, relay_id=launch.assigned_relay_id, now=now)
        != TRANSPORT_RELAY_CONNECTED
    ):
        return "deadline_expiry"
    return None


def extend_launch_message_expiry(
    conn: Any, *, message_id: str, expires_at: datetime
) -> None:
    """Realign the instruction message TTL to the launch's live deadline.

    The message is created under the launch's create-time deadline, and both
    pickup and retry move that deadline later. A recipient inserted under the
    stale TTL is swept to ``expired`` within a second and the mandate is never
    delivered. Only ever extend, never shorten.
    """
    p = marker(conn)
    conn.execute(
        f"UPDATE session_messages SET expires_at={p} "
        f"WHERE message_id={p} AND expires_at < {p}",
        (
            instant_parameter(conn, parse_instant(expires_at)),
            message_id,
            instant_parameter(conn, parse_instant(expires_at)),
        ),
    )


def start_pickup_window(
    conn: Any, launch: LaunchRecord, *, now: datetime | str
) -> datetime:
    """Return the deadline a launch's spawn window runs to from this pickup.

    The window keeps the length it was requested with, measured from when the
    launch was queued, and the instruction message follows it. A launch whose
    queue wait is already exhausted is closed with its evidence and refused.
    """
    reason = queue_wait_exhausted(conn, launch, now=now)
    if reason is not None:
        _expire_at_deadline(conn, launch, now=now, closure_reason=reason)
        conn.commit()
        raise SessionLaunchError(
            "expired",
            f"launch waited past its queue bound ({reason}); "
            f"retry it with `yoke session-control launch retry {launch.launch_id}`",
        )
    window = parse_time(launch.deadline_at) - parse_time(_queued_since(launch))
    deadline = add_seconds(now, int(window.total_seconds()))
    extend_launch_message_expiry(
        conn, message_id=launch.message_id, expires_at=deadline
    )
    return deadline


def _expire_launching(
    conn: Any,
    launch: LaunchRecord,
    *,
    attempt: Any,
    now: datetime | str,
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
    now: datetime | str,
    closure_reason: str = "deadline_expiry",
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
    receipt = None
    if registration and launch.registered_session_id:
        p = marker(conn)
        receipt = conn.execute(
            f"SELECT state FROM session_message_recipients "
            f"WHERE message_id={p} AND session_id={p}",
            (launch.message_id, launch.registered_session_id),
        ).fetchone()
    receipt_state = str(value(receipt, "state", 0)) if receipt is not None else ""
    unacknowledged = bool(launch.registered_session_id) and receipt_state in (
        "pending",
        "injected",
        "expired",
    )
    result_code = (
        "launch_acknowledgement_missing"
        if unacknowledged
        else "registration_deadline"
        if registration
        else "launch_deadline"
    )
    evidence = closure_evidence(
        conn,
        launch=launch,
        result_code=result_code,
        closure_reason=closure_reason,
        relay_id=launch.assigned_relay_id,
        machine_id=launch.assigned_machine_id,
        started_at=launch.awaiting_registration_at or launch.launching_at,
        now=now,
    )
    if unacknowledged:
        evidence["receipt_state"] = receipt_state
        evidence["recovery"] = (
            "Inspect the native turn and hook evidence, then retry the launch; "
            "the injected message was never acknowledged."
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
    now: datetime | str | None = None,
    launch_id: str | None = None,
    project_id: int | None = None,
) -> list[LaunchRecord]:
    """Close expired queues and surface uncertain expired native attempts."""
    current = utc_now() if now is None else parse_instant(now)
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
                    add_seconds(value(row, "started_at", 3), LAUNCH_LEASE_SECONDS)
                )
                if deadline_passed or (
                    lease_passed
                    and not native_attempt_pending(conn, launch, now=current)
                ):
                    changed.append(
                        _expire_launching(conn, launch, attempt=row, now=current)
                    )
            elif launch.state in QUEUED_LAUNCH_STATES:
                reason = queue_wait_exhausted(conn, launch, now=current)
                if reason is not None:
                    changed.append(
                        _expire_at_deadline(
                            conn, launch, now=current, closure_reason=reason
                        )
                    )
            elif deadline_passed:
                changed.append(_expire_at_deadline(conn, launch, now=current))
        conn.commit()
        return changed
    except Exception:
        conn.rollback()
        raise


__all__ = [
    "LAUNCH_QUEUE_WAIT_SECONDS",
    "extend_launch_message_expiry",
    "queue_wait_exhausted",
    "settle_launch_deadlines",
    "start_pickup_window",
]
