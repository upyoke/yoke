"""Route failed wakes to project steering or the original sender.

The original receipt and its bounded retries remain authoritative. This is
only a failure notice, recorded through the existing message store. Org-owned
engine messages notify the affected session's actor. A notice never raises another.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Mapping

from yoke_contracts.session_control.models import RecipientSelector
from yoke_contracts.session_control.wake_delivery import delivery_attempt_diagnostic
from yoke_core.domain.session_item_scope import session_item_scope
from yoke_core.domain.session_message_recipient_scope import (
    recipient_owner,
    recipient_policy,
)
from yoke_core.domain.session_message_steering import (
    resolve_steering_address,
    seat_session_id,
)
from yoke_core.domain.session_message_selectors import resolve_recipients
from yoke_core.domain.session_message_store import idempotent_message, insert_message
from yoke_core.domain.session_message_starvation import turn_in_flight
from yoke_core.domain.session_message_types import parse_timestamp
from yoke_core.domain.session_relay_storage import marker
from yoke_core.domain.steering_message_recipients import record_steering_recipient
from yoke_core.domain.actor_message_recipients import ResolvedActorRecipient
from yoke_core.domain.session_explicit_wake import explicit_stopped_wake_requested


NOTICE_PREFIX = "native-wake-failed"


def notify_failed_wake(
    conn: Any,
    row: Mapping[str, Any],
    *,
    now: datetime,
    max_attempts: int,
) -> str | None:
    """Record one notice per envelope and failure, without committing."""
    p = marker(conn)
    message_id, session_id = str(row["message_id"]), str(row["session_id"])
    attempt = conn.execute(
        "SELECT result_code,evidence,completed_at FROM session_message_attempts "
        f"WHERE message_id={p} AND target_session_id={p} "
        "AND attempt_kind IN ('wake_relay','wake_broker') "
        "AND completed_at IS NOT NULL ORDER BY started_at DESC,attempt_id DESC LIMIT 1",
        (message_id, session_id),
    ).fetchone()
    exhausted = int(row.get("wake_attempt_count") or 0) >= max_attempts
    if attempt is None:
        return None
    evidence = json.loads(str(attempt[1] or "{}"))
    reason = delivery_attempt_diagnostic(attempt[0], evidence)
    if not reason:
        return None
    original = conn.execute(
        "SELECT m.idempotency_key,r.state,r.acknowledged_at,"
        "m.sender_session_id,m.sender_actor_id FROM session_messages m "
        "JOIN session_message_recipients r ON r.message_id=m.message_id "
        f"WHERE m.message_id={p} AND r.session_id={p}",
        (message_id, session_id),
    ).fetchone()
    if (
        original is None
        or original[1] == "acknowledged"
        or original[2] is not None
        or str(original[0] or "").startswith(f"{NOTICE_PREFIX}:")
    ):
        return None
    skipped = str(attempt[0]).startswith("skipped_")
    if skipped and evidence.get("skip_reason") == "surface_wake_operator_driven":
        # Hook delivery on the operator's next turn is this surface's route.
        # Having no relay wake is intentional, not a failed delivery.
        return None
    explicit_skip = skipped and explicit_stopped_wake_requested(
        row.get("routing_snapshot")
    )
    if (
        (attempt[0] == "outcome_unknown" or skipped)
        and not exhausted
        and not explicit_skip
    ):
        # A busy target still has a hook coming. Only a completed tool call
        # after the uncertain or skipped wake proves another opportunity passed.
        completed = parse_timestamp(attempt[2])
        opportunity = parse_timestamp(row.get("last_tool_call_at"))
        if (
            turn_in_flight(row) is not None
            or completed is None
            or opportunity is None
            or opportunity <= completed
        ):
            return None
    failure = "wake_attempts_exhausted" if exhausted else str(attempt[0])
    key = f"{NOTICE_PREFIX}:{message_id}:{session_id}:{failure}"
    if idempotent_message(conn, sender_actor_id=None, idempotency_key=key) is not None:
        return None
    project_id, _ = recipient_owner(row)
    policy = recipient_policy(conn, row)
    address, seat_id, seat = None, None, None
    recipients = []
    if project_id is not None:
        held = session_item_scope(conn, session_id)
        project_id = held.project_id if held is not None else project_id
        selector = RecipientSelector(
            steering=True, steering_scope={"project_id": project_id}
        )
        address = resolve_steering_address(conn, selector, sender_session_id=session_id)
        seat_id, seat = seat_session_id(conn, address)
        if seat_id:
            recipients = resolve_recipients(
                conn, selector, now=now, steering_target=address.coverage_target()
            )
    sender_session = str(original[3] or "")
    sender_actor = original[4]
    actor_reason = "original_sender"
    if project_id is None and sender_actor is None:
        sender_session = ""
        owner = conn.execute(
            f"SELECT actor_id FROM harness_sessions WHERE session_id={p}", (session_id,)
        ).fetchone()
        sender_actor = owner[0] if owner is not None else None
        actor_reason = "affected_session_actor"
    if sender_session:
        senders = resolve_recipients(
            conn, RecipientSelector(session_ids=[sender_session]), now=now
        )
        recipients = list({r.session_id: r for r in [*recipients, *senders]}.values())
    actors = []
    if sender_actor is not None:
        actor = conn.execute(
            f"SELECT kind FROM actors WHERE id={p}", (sender_actor,)
        ).fetchone()
        if actor is not None and (project_id is None or actor[0] == "human"):
            org_id = policy.org_id
            if project_id is not None:
                org_id = int(
                    conn.execute(
                        f"SELECT org_id FROM projects WHERE id={p}", (project_id,)
                    ).fetchone()[0]
                )
            actors = [
                ResolvedActorRecipient(
                    int(sender_actor), None, {org_id}, [actor_reason]
                )
            ]
    details, created = insert_message(
        conn,
        sender_actor_id=None,
        sender_session_id=None,
        sender_surface=None,
        body=(
            f"Native message wake failed: {failure}. Session {session_id}, "
            f"message {message_id}: {reason}. "
            f"Read yoke messages get {message_id} and yoke session-control evidence "
            f"get --session {session_id}; repair the named cause before waking or "
            "relaunching the holder through the existing session-control path."
        ),
        selector_snapshot={
            **({"steering": True, "steering_scope": address.scope} if address else {}),
            "session_ids": [sender_session] if sender_session else [],
            "actors": [str(sender_actor)] if actors else [],
        },
        idempotency_key=key,
        idempotency_intent_only=True,
        created_at=now,
        expires_at=now + timedelta(hours=policy.expiry_hours),
        recipients=recipients,
        actor_recipients=actors,
        wake_after_by_project={
            **({project_id: now} if project_id is not None else {}),
            **{r.project_id: now for r in recipients},
        },
    )
    if not created:
        return None
    notice_id = str(details["message_id"])
    if address is not None:
        record_steering_recipient(
            conn,
            message_id=notice_id,
            scope=address.scope,
            project_id=project_id,
            sender_item_id=address.sender_item_id,
            seat_session_id=seat_id,
            seat_claim_id=int(seat["claim_id"]) if seat else None,
            created_at=now,
        )
    return notice_id
