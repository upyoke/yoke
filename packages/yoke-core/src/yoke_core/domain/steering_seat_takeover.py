"""Retire exited steering holders before the normal serialized acquire."""

from __future__ import annotations

from typing import Any

from yoke_contracts.session_control.capabilities import surface_wake_authority
from yoke_contracts.session_control.models import RecipientSelector
from yoke_contracts.timestamps import utc_now
from yoke_core.domain import db_backend
from yoke_core.domain.session_message_service import send_message
from yoke_core.domain.session_native_process_observation import (
    current_native_process_observation,
)
from yoke_core.domain.session_resume_in_flight import resume_in_flight
from yoke_core.domain.session_state import session_presence
from yoke_core.domain.sessions_analytics import SessionError
from yoke_core.domain.sessions_lifecycle_claim_release import release_claim_by_id
from yoke_core.domain.steering_seat_holder import holder_label
from yoke_core.domain.work_claim_targets import decode_scope, encode_scope


def _exit_at(conn: Any, row: dict[str, Any], *, now: Any) -> Any:
    if row.get("ended_at") or row.get("terminated_at"):
        return row.get("ended_at") or row["terminated_at"]
    if session_presence(row) != "gone":
        return None
    if resume_in_flight(conn, str(row["session_id"]), now=now) is not None:
        return None
    if (
        surface_wake_authority(row.get("executor_surface")) == "operator"
        or current_native_process_observation(row) is not None
    ):
        return row["native_process_gone_at"]
    return None


def release_exited_seats(
    conn: Any,
    rows: list[Any],
    *,
    session_id: str,
    target: Any,
    actor_id: int | None,
) -> bool:
    """Check every overlap before releasing any; live holders keep their seats.

    Release owns its commit, so the caller must restart normal acquire after
    this returns true to recover its session and project locks.
    """
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    now = utc_now()
    exited = []
    for row in rows:
        claim = dict(row)
        holder = conn.execute(
            f"SELECT * FROM harness_sessions WHERE session_id = {marker}",
            (claim["session_id"],),
        ).fetchone()
        exit_at = _exit_at(conn, dict(holder), now=now) if holder else None
        if exit_at is None:
            raise SessionError(
                "ALREADY_CLAIMED",
                f"Steering scope {target.scope_json()} overlaps the live scope "
                f"{encode_scope(decode_scope(claim['scope']))} already held by "
                f"{holder_label(conn, claim)} (claim {claim['id']}); "
                f"ask that holder for the seat with `yoke say --session "
                f"{claim['session_id']}`. Inspect live seats with "
                f"`yoke claims steering list --project {int(target.project_id)} "
                "--active-only`.",
            )
        exited.append((claim, exit_at, bool(holder["terminated_at"])))
    if not exited:
        return False
    sender = conn.execute(
        f"SELECT actor_id FROM harness_sessions WHERE session_id = {marker}",
        (session_id,),
    ).fetchone()
    # Release owns a commit. Retire one seat, then restart acquire with fresh
    # session/project locks before inspecting or retiring the next overlap.
    claim, exit_at, terminated = exited[0]
    old_session = str(claim["session_id"])
    reason = (
        f"steering seat taken over by session {session_id}: holder exited at {exit_at}"
    )
    # Termination permanently forbids messaging and resume on this session.
    if not terminated:
        send_message(
            conn,
            actor_id=actor_id if actor_id is not None else sender["actor_id"],
            sender_session_id=session_id,
            selector=RecipientSelector(session_ids=[old_session]),
            body=(
                f"Your steering seat was taken over by session {session_id} "
                f"because you exited at {exit_at}. You no longer hold that "
                "seat or its paired strategy-document lock. Reacquire with "
                f"`yoke claims steering acquire --project {target.project_id} "
                "--reason TEXT` (add --doc SLUG for a document seat) "
                "before steering again."
            ),
            idempotency_key=f"steering-takeover:{session_id}:{old_session}:{exit_at}",
            now=now,
            commit=False,
        )
    release_claim_by_id(conn, int(claim["id"]), reason=reason)
    return True
