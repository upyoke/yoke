"""Recover an uncontested worker after its launch window elapsed."""

from __future__ import annotations

from typing import Any

from yoke_contracts.refusal_recovery import compose_refusal
from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import instant_parameter
from yoke_core.domain.session_launch_deadlines import extend_launch_message_expiry
from yoke_core.domain.session_launch_store import (
    add_seconds, begin_mutation, get_launch, marker, parse_time, update_launch, value,
)
from yoke_core.domain.session_launch_types import (
    DEFAULT_LAUNCH_DEADLINE_SECONDS, LaunchRecord, SessionLaunchError,
)
from yoke_core.domain.session_relay_evidence import merge_redacted_evidence
from yoke_core.domain.work_claim_target_sql import scope_int_sql


def taken_over(launch: LaunchRecord, takeover: str) -> None:
    raise SessionLaunchError(
        "launch_taken_over",
        compose_refusal(
            f"Launch {launch.launch_id} was taken over",
            evaluated=takeover,
            recovery="Stop this worker without claiming work; inspect the named "
            "launch or session with `yoke session-control launch get LAUNCH-ID` "
            "or `yoke sessions get SESSION-ID`, then coordinate with its holder.",
        ),
    )


def accept_late_launch(
    conn: Any, launch: LaunchRecord, *, session_id: str, now: Any,
) -> LaunchRecord:
    """Called under the launch lock, after verifying the worker's authority."""
    if launch.state == "cancelled":
        taken_over(launch, "launch was cancelled")
    if launch.state not in {"failed", "expired", "awaiting_registration"}:
        taken_over(launch, f"retry or replacement is in state {launch.state}")
    if launch.item_id is not None:
        p = marker(conn)
        if db_backend.connection_is_postgres(conn):
            conn.execute(f"SELECT id FROM items WHERE id={p} FOR UPDATE", (launch.item_id,))
        scope = scope_int_sql(conn, "scope", "item_id")
        holder = conn.execute(
            f"SELECT session_id FROM work_claims WHERE target_kind='item' "
            f"AND {scope}={p} AND released_at IS NULL AND session_id<>{p} LIMIT 1",
            (launch.item_id, session_id),
        ).fetchone()
        if holder:
            taken_over(launch, f"active claim belongs to session {holder[0]}")
        replacement = conn.execute(
            f"SELECT launch_id, registered_session_id FROM session_launches "
            f"WHERE item_id={p} AND launch_id<>{p} AND "
            "(state IN ('queued','assigned','launching','awaiting_registration',"
            "'outcome_unknown','succeeded') OR created_at>=" + p + ") "
            "ORDER BY created_at DESC, launch_id LIMIT 1",
            (launch.item_id, launch.launch_id, instant_parameter(conn, launch.created_at)),
        ).fetchone()
        if replacement:
            taken_over(launch, f"replacement launch {replacement[0]}; session {replacement[1] or 'not registered'}")
    p = marker(conn)
    message = conn.execute(
        f"SELECT cancellation_reason FROM session_messages WHERE message_id={p}",
        (launch.message_id,),
    ).fetchone()
    reason = value(message, "cancellation_reason", 0) if message else None
    if reason and reason not in {"launch_failed", "launch_expired"}:
        taken_over(launch, f"message cancelled: {reason}")
    deadline = add_seconds(now, DEFAULT_LAUNCH_DEADLINE_SECONDS)
    extend_launch_message_expiry(conn, message_id=launch.message_id, expires_at=deadline)
    conn.execute(
        "UPDATE session_message_recipients SET state='pending', expired_at=NULL, "
        "cancelled_at=NULL, acknowledged_at=NULL, injection_lease_id=NULL, "
        "injection_leased_at=NULL, injection_lease_expires_at=NULL "
        f"WHERE message_id={p} AND session_id={p}",
        (launch.message_id, session_id),
    )
    return update_launch(
        conn, launch.launch_id, state="awaiting_registration", deadline_at=deadline,
        completed_at=None, result_code="accepted_late",
        result_evidence=merge_redacted_evidence(launch.result_evidence, {
            "accepted_late": parse_time(now).isoformat(),
            "previous_launch_state": launch.state,
            "previous_launch_result": launch.result_code,
            "previous_launch_deadline": parse_time(launch.deadline_at).isoformat(),
        }),
    )


def accept_late_acknowledgement(
    conn: Any, *, message_id: str, session_id: str, now: Any,
) -> None:
    """Ordinary mail keeps its TTL; only a launch's own receipt can recover."""
    begin_mutation(conn)
    p = marker(conn)
    row = conn.execute(
        f"SELECT launch_id FROM session_launches WHERE message_id={p}", (message_id,),
    ).fetchone()
    if row is None:
        return
    launch = get_launch(conn, str(row[0]), for_update=True)
    receipt = conn.execute(
        f"SELECT state FROM session_message_recipients WHERE message_id={p} AND session_id={p}",
        (message_id, session_id),
    ).fetchone()
    if receipt is None:
        return
    if launch.registered_session_id != session_id:
        taken_over(launch, f"retry or rebound session {launch.registered_session_id or launch.native_session_id or 'not registered'}")
    if launch.state == "succeeded":
        return
    if launch.state in {"failed", "expired", "cancelled"} or parse_time(now) >= parse_time(launch.deadline_at):
        accept_late_launch(conn, launch, session_id=session_id, now=now)
