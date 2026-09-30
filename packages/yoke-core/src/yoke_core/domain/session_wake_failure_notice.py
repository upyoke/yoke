"""Route a refused or exhausted message wake to its covering steering seat.

The original receipt and its bounded retries remain authoritative. This is
only a failure notice, recorded through the existing role-addressed message
store so a seat handoff cannot lose it. A notice never raises another notice.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Mapping

from yoke_contracts.session_control.models import RecipientSelector
from yoke_contracts.session_control.wake_delivery import delivery_attempt_diagnostic
from yoke_core.domain.actors import SYSTEM_COMPONENT_YOKE_CORE, seed_system_actor
from yoke_core.domain.session_item_scope import session_item_scope
from yoke_core.domain.session_message_authorization import project_policy
from yoke_core.domain.session_message_steering import (
    resolve_steering_address,
    seat_session_id,
)
from yoke_core.domain.session_message_selectors import resolve_recipients
from yoke_core.domain.session_message_store import insert_message
from yoke_core.domain.session_relay_storage import marker
from yoke_core.domain.steering_message_recipients import record_steering_recipient


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
        "SELECT result_code,evidence FROM session_message_attempts "
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
        f"SELECT idempotency_key FROM session_messages WHERE message_id={p}",
        (message_id,),
    ).fetchone()
    if original is None or str(original[0] or "").startswith(f"{NOTICE_PREFIX}:"):
        return None
    failure = "wake_attempts_exhausted" if exhausted else str(attempt[0])
    held = session_item_scope(conn, session_id)
    project_id = held.project_id if held is not None else int(row["project_id"])
    selector = RecipientSelector(
        steering=True, steering_scope={"project_id": project_id}
    )
    address = resolve_steering_address(
        conn,
        selector,
        sender_session_id=session_id,
    )
    policy = project_policy(conn, project_id)
    recipients = resolve_recipients(
        conn, selector, now=now, steering_target=address.coverage_target()
    )
    details, created = insert_message(
        conn,
        sender_actor_id=seed_system_actor(conn, SYSTEM_COMPONENT_YOKE_CORE),
        sender_session_id=None,
        sender_surface=None,
        body=(
            f"Native message wake needs steering: {failure}. Session {session_id}, "
            f"message {message_id}: {reason}. "
            f"Read yoke messages get {message_id} and yoke session-control evidence "
            f"get --session {session_id}; repair the named cause before waking or "
            "relaunching the holder through the existing session-control path."
        ),
        selector_snapshot={"steering": True, "steering_scope": address.scope},
        idempotency_key=f"{NOTICE_PREFIX}:{message_id}:{session_id}:{failure}",
        idempotency_intent_only=True,
        created_at=now,
        expires_at=now + timedelta(hours=policy.expiry_hours),
        recipients=recipients,
        actor_recipients=[],
        wake_after_by_project={project_id: now},
    )
    if not created:
        return None
    notice_id = str(details["message_id"])
    seat_id, seat = seat_session_id(conn, address)
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
