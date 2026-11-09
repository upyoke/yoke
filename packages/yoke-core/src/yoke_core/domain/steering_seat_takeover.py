"""Release terminal holders or explicitly take over overlapping steering seats."""

from __future__ import annotations

from typing import Any

from yoke_contracts.session_control.models import RecipientSelector
from yoke_contracts.timestamps import utc_now
from yoke_core.domain import db_backend
from yoke_core.domain.session_message_service import send_message
from yoke_core.domain.sessions_analytics import SessionError
from yoke_core.domain.sessions_lifecycle_claim_release import release_claim_by_id
from yoke_core.domain.steering_seat_holder import holder_label
from yoke_core.domain.work_claim_targets import decode_scope, encode_scope


def release_overlapping_seats(
    conn: Any,
    rows: list[Any],
    *,
    session_id: str,
    target: Any,
    actor_id: int | None,
    take_over: bool,
    reason: str | None,
) -> bool:
    """Check every overlap before releasing any; require consent for live holders.

    Release owns its commit, so the caller must restart normal acquire after
    this returns true to recover its session and project locks.
    """
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    now = utc_now()
    releasable = []
    for row in rows:
        claim = dict(row)
        if str(claim["session_id"]) == session_id:
            continue
        holder = conn.execute(
            f"SELECT * FROM harness_sessions WHERE session_id = {marker}",
            (claim["session_id"],),
        ).fetchone()
        exit_at = (holder["ended_at"] or holder["terminated_at"]) if holder else None
        if exit_at is None and not take_over:
            raise SessionError(
                "ALREADY_CLAIMED",
                f"Steering scope {target.scope_json()} overlaps the live scope "
                f"{encode_scope(decode_scope(claim['scope']))} already held by "
                f"{holder_label(conn, claim)} (claim {claim['id']}); "
                "take it explicitly with `yoke claims steering acquire "
                f"--project {int(target.project_id)} "
                + (f"--doc {target.scope['document']} " if target.scope.get('document') else "")
                + "--take-over --reason TEXT`. Inspect live seats with "
                f"`yoke claims steering list --project {int(target.project_id)} "
                "--active-only`.",
            )
        releasable.append((claim, exit_at, bool(holder and holder["terminated_at"])))
    if not releasable:
        return False
    sender = conn.execute(
        f"SELECT actor_id FROM harness_sessions WHERE session_id = {marker}",
        (session_id,),
    ).fetchone()
    # Release owns a commit. Retire one seat, then restart acquire with fresh
    # session/project locks before inspecting or retiring the next overlap.
    claim, exit_at, terminated = releasable[0]
    old_session = str(claim["session_id"])
    release_reason = reason if take_over else (
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
                f"Your steering seat was taken over by session {session_id}. "
                f"Reason: {release_reason}. You no longer hold that "
                "seat or its paired strategy-document lock. Reacquire with "
                f"`yoke claims steering acquire --project {target.project_id} "
                "--reason TEXT` (add --doc SLUG for a document seat) "
                "before steering again."
            ),
            idempotency_key=f"steering-takeover:{session_id}:{claim['id']}",
            now=now,
            commit=False,
        )
    release_claim_by_id(conn, int(claim["id"]), reason=release_reason)
    return True
