"""Wake a relay worker whose surface cannot hold a turn with promised work.

A relay-launched worker on a surface whose denied Stop does not continue the
turn (``relay_stop_denial_continuation = "none"``, or a surface whose turn
ends on ``SessionEnd``) can only be allowed to stop while it still holds a
live item claim. Nothing else resumes it: vendor-error resume covers provider
failures, not a worker that ended its own turn between workflow stages. So
the Stop gate queues the same explicit stopped-route wake
``yoke session-control session wake`` sends, and the relay resumes the native
once its turn has ended.

The wake is bounded by the hold ledger the reinjection ceiling and cooldown
already read, and each queued wake counts as one hold. A wake the ceiling or
the wake path refuses is mailed to the project's steering seat with the named
reason and recovery, because a worker that keeps stopping is a decision for
steering, not another automatic wake.
"""

from __future__ import annotations

from typing import Any, Mapping

from yoke_contracts.session_control.models import RecipientSelector

from yoke_core.domain import db_backend
from yoke_core.domain.session_message_types import SessionMessageError, utc_now
from yoke_core.domain.session_recovery_facts import (
    promised_work_holds,
    record_promised_work_hold,
)
from yoke_core.domain.turn_end_unfinished_work import recovery_for


REASON_CAP_REACHED = "reinjection_cap_reached"
REASON_RELAY_WAKE_QUEUED = "relay_continuation_wake_queued"
REASON_RELAY_WAKE_REFUSED = "relay_continuation_wake_refused"
ALARM_KEY_PREFIX = "relay-continuation-alarm"


def _session_actor(conn: Any, session_id: str) -> int | None:
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    row = conn.execute(
        f"SELECT actor_id FROM harness_sessions WHERE session_id={marker}",
        (session_id,),
    ).fetchone()
    if row is None or row[0] is None:
        return None
    return int(row[0])


def _item_ref(conn: Any, item_id: Any) -> str:
    from yoke_core.domain.project_identity import render_item_ref

    return render_item_ref(conn, int(item_id))


def continuation_notice(ref: str, claim: Mapping[str, Any], attempt: int) -> str:
    """The body the woken worker reads first: why it woke and how to resume."""
    return (
        f"Your previous turn ended while this session still holds the work "
        f"claim on {ref}, and this surface cannot keep a turn open, so Yoke "
        "woke you to continue. Nothing about your item, lane or claim "
        "changed. Read the item's Progress Log, then `git status` and "
        "`git log` in your lane, and carry on from your last committed "
        f"state. {recovery_for(dict(claim))} This is automatic continuation "
        f"{attempt}; a worker that keeps stopping is reported to steering "
        "instead of woken again."
    )


def _alarm_steering(
    conn: Any,
    *,
    actor_id: int | None,
    session_id: str,
    ref: str,
    failure: str,
    detail: str,
    key: str,
) -> None:
    """Mail the steering seat once per stop the automatic wake did not cover.

    A refused alarm cannot raise another one; the caller's deferred record
    still carries the failure for anyone reading the worker's evidence.
    """
    if actor_id is None:
        return
    from yoke_core.domain.session_message_service import send_message

    try:
        send_message(
            conn,
            actor_id=actor_id,
            sender_session_id=session_id,
            selector=RecipientSelector(steering=True),
            body=(
                f"Relay worker {session_id} stopped holding {ref} with work "
                f"left, and automatic continuation did not wake it: {failure}. "
                f"{detail} Recovery: read `yoke session-control evidence get "
                f"--session {session_id}`, then wake it with `yoke "
                f"session-control session wake {session_id}` or restaff {ref}."
            ),
            idempotency_key=key,
            now=utc_now(),
        )
    except Exception:
        conn.rollback()


def continue_relay_worker(
    conn: Any,
    *,
    session_id: str,
    claim: Mapping[str, Any],
    at_cap: bool,
) -> str:
    """Queue one continuation wake or alarm steering; return the reason."""
    from yoke_core.domain.session_manual_wake import request_session_wake

    item_id = claim["item_id"]
    ref = _item_ref(conn, item_id)
    actor_id = _session_actor(conn, session_id)
    _, holds = promised_work_holds(conn, session_id=session_id, item_id=item_id)
    if at_cap:
        _alarm_steering(
            conn,
            actor_id=actor_id,
            session_id=session_id,
            ref=ref,
            failure=REASON_CAP_REACHED,
            detail=(
                f"It was already woken {holds} time(s) for this item, or "
                "stopped again inside the cooldown."
            ),
            key=f"{ALARM_KEY_PREFIX}:{session_id}:{item_id}:{holds}:cap",
        )
        return REASON_CAP_REACHED
    try:
        if actor_id is None:
            raise SessionMessageError(
                "wake_actor_unresolved",
                "The worker session records no actor to wake it as.",
            )
        request_session_wake(
            conn,
            actor_id=actor_id,
            caller_session_id=None,
            session_id=session_id,
            public_ref=None,
            prompt=continuation_notice(ref, claim, holds + 1),
        )
    except SessionMessageError as exc:
        _alarm_steering(
            conn,
            actor_id=actor_id,
            session_id=session_id,
            ref=ref,
            failure=exc.code,
            detail=str(exc),
            key=f"{ALARM_KEY_PREFIX}:{session_id}:{item_id}:{holds}:{exc.code}",
        )
        return REASON_RELAY_WAKE_REFUSED
    record_promised_work_hold(
        conn, session_id=session_id, item_id=item_id, at=utc_now()
    )
    conn.commit()
    return REASON_RELAY_WAKE_QUEUED


__all__ = [
    "REASON_CAP_REACHED",
    "REASON_RELAY_WAKE_QUEUED",
    "REASON_RELAY_WAKE_REFUSED",
    "continuation_notice",
    "continue_relay_worker",
]
