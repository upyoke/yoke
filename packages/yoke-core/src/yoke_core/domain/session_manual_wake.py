"""One-shot explicit wake requests over the durable message relay."""

from __future__ import annotations

import json
from datetime import datetime
from time import monotonic, sleep
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

from yoke_contracts.session_control.models import RecipientSelector
from yoke_contracts.session_control.wake import EXPLICIT_WAKE_ROUTING_FLAG
from yoke_contracts.session_control.wake_instruction import native_wake_instruction
from yoke_core.domain import db_backend
from yoke_core.domain.session_message_authorization import (
    authorize_recipients,
)
from yoke_core.domain.session_message_routing import messageability
from yoke_core.domain.session_message_selectors import resolve_recipients
from yoke_core.domain.session_message_service import send_message
from yoke_core.domain.session_message_store import (
    begin_message_mutation,
    message_details,
)
from yoke_core.domain.session_message_types import (
    ResolvedRecipient,
    SessionMessageError,
    utc_now,
)
from yoke_core.domain.session_operator_authority import (
    session_control_target,
)
from yoke_core.domain.session_relay_machine_versions import (
    connected_relay_routes,
    machine_surface_versions,
)
from yoke_core.domain.session_wake_idempotency import recent_wake_blocker


SESSION_WAKE_RESULT_WAIT_SECONDS = 10.0
_RESULT_POLL_SECONDS = 0.25


def _selector(*, session_id: str | None, item_ref: str | None) -> RecipientSelector:
    return RecipientSelector(
        session_ids=[session_id] if session_id else [],
        item_refs=[item_ref] if item_ref else [],
    )


def _message_id(actor_id: int, idempotency_key: str | None) -> str:
    if idempotency_key:
        intent = f"yoke:session-wake:{actor_id}:{idempotency_key}"
        return str(uuid5(NAMESPACE_URL, intent))
    return str(uuid4())


def _one_recipient(recipients: list[ResolvedRecipient]) -> ResolvedRecipient:
    if not recipients:
        raise SessionMessageError(
            "wake_target_unclaimed",
            "The wake target resolved no current session; verify the session id or "
            "acquire the item work claim before retrying.",
        )
    if len(recipients) > 1:
        raise SessionMessageError(
            "wake_target_ambiguous",
            "The item resolves multiple current claim holders; retry with one exact "
            "SESSION-ID.",
        )
    return recipients[0]


def _stopped_route(
    conn: Any,
    recipient: ResolvedRecipient,
    target: dict[str, Any],
    *,
    now: datetime,
) -> dict[str, Any]:
    routes = connected_relay_routes(conn, now=now)
    versions = machine_surface_versions(
        routes,
        machine_id=recipient.machine_id,
        project_id=recipient.project_id,
    )
    routing = messageability(
        target,
        liveness=recipient.liveness,
        machine_surface_versions=versions,
        force_stopped_route=True,
    )
    if target.get("terminated_at") or routing.get("reason") == "session_terminated":
        raise SessionMessageError(
            "session_terminated",
            "A terminated session cannot be woken; create a new session instead.",
        )
    if not routing.get("messageable") or routing.get("wake_interface") == "none":
        raise SessionMessageError(
            "manual_wake_route_unavailable",
            "The target has no version-qualified stopped-session wake route. Run "
            "`yoke relay status`, start or upgrade its machine relay, then retry.",
        )
    return routing


def _wake_result(
    details: dict[str, Any],
    *,
    target_session_id: str,
    target_liveness: str,
    routing: dict[str, Any],
    deduplicated: bool,
) -> dict[str, Any]:
    wake_attempts = [
        attempt
        for attempt in details.get("attempts", [])
        if attempt.get("attempt_kind") in {"wake_relay", "wake_broker"}
    ]
    attempt = wake_attempts[-1] if wake_attempts else None
    message_id = str(details["message_id"])
    recipient = details["recipients"][0]
    result_code = str((attempt or {}).get("result_code") or "queued")
    evidence = dict((attempt or {}).get("evidence") or {})
    if attempt is None:
        evidence = {
            "target_liveness": target_liveness,
            "wake_interface": routing.get("wake_interface"),
            "wake_operation": routing.get("wake_operation"),
        }
    recovery = None
    if attempt is None or not attempt.get("completed_at"):
        recovery = f"yoke messages get {message_id}"
    return {
        "target_session_id": target_session_id,
        "target_liveness": target_liveness,
        "message_id": message_id,
        "result_code": result_code,
        "attempt": attempt,
        "evidence": evidence,
        "recovery": recovery,
        "deduplicated": deduplicated,
        "wake_attempt_count": int(recipient.get("wake_attempt_count") or 0),
        "last_wake_at": recipient.get("last_wake_at"),
    }


def wait_for_session_wake_result(
    conn: Any,
    result: dict[str, Any],
    *,
    wait_seconds: float = SESSION_WAKE_RESULT_WAIT_SECONDS,
) -> dict[str, Any]:
    """Read back the first relay result without exceeding function-call timeout."""
    deadline = monotonic() + max(0.0, float(wait_seconds))
    latest = dict(result)
    while True:
        details = message_details(conn, str(result["message_id"]))
        attempts = [
            attempt
            for attempt in details.get("attempts", [])
            if attempt.get("attempt_kind") in {"wake_relay", "wake_broker"}
        ]
        if attempts:
            attempt = attempts[-1]
            recipient = details["recipients"][0]
            latest = {
                **result,
                "attempt": attempt,
                "result_code": str(attempt.get("result_code") or "in_progress"),
                "evidence": dict(attempt.get("evidence") or {}),
                "recovery": (
                    None
                    if attempt.get("completed_at")
                    else f"yoke messages get {result['message_id']}"
                ),
                "wake_attempt_count": int(recipient.get("wake_attempt_count") or 0),
                "last_wake_at": recipient.get("last_wake_at"),
            }
            if attempt.get("result_code"):
                return latest
        remaining = deadline - monotonic()
        if remaining <= 0:
            return latest
        conn.commit()
        sleep(min(_RESULT_POLL_SECONDS, remaining))


def request_session_wake(
    conn: Any,
    *,
    actor_id: int,
    caller_session_id: str | None,
    session_id: str | None,
    item_ref: str | None,
    prompt: str | None,
    idempotency_key: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Queue one forced stopped-route wake and return body-free attempt facts."""
    current = now or utc_now()
    target_selector = _selector(session_id=session_id, item_ref=item_ref)
    message_id = _message_id(actor_id, idempotency_key)
    begin_message_mutation(conn)
    try:
        recipient = _one_recipient(
            resolve_recipients(conn, target_selector, now=current)
        )
        policy = authorize_recipients(conn, actor_id=actor_id, recipients=[recipient])[
            recipient.project_id
        ]
        target = session_control_target(conn, recipient.session_id)
        routing = _stopped_route(conn, recipient, target, now=current)
        blocker = recent_wake_blocker(
            conn,
            session_id=recipient.session_id,
            now=current,
            grace_seconds=policy.wake_ack_grace_seconds,
            exclude_message_id=message_id,
            include_queued_explicit=True,
        )
        if blocker:
            retry = blocker.get("retry_after") or "after the current attempt settles"
            raise SessionMessageError(
                "wake_in_flight",
                f"Native wake refused: {blocker['reason']} for message "
                f"{blocker['message_id']} (wake_attempt_count="
                f"{blocker['wake_attempt_count']}, last_wake_at="
                f"{blocker.get('last_wake_at') or 'none'}). Inspect `yoke messages "
                f"get {blocker['message_id']}` and retry {retry}.",
            )
        final_prompt = prompt or native_wake_instruction(message_id)
        created = send_message(
            conn,
            message_id=message_id,
            actor_id=actor_id,
            sender_session_id=caller_session_id,
            selector=target_selector,
            body=final_prompt,
            idempotency_key=idempotency_key,
            now=current,
            commit=False,
        )
        message_id = str(created["message_id"])
        details = message_details(conn, message_id)
        recipients = details.get("recipients", [])
        if len(recipients) != 1 or recipients[0]["session_id"] != recipient.session_id:
            raise SessionMessageError(
                "wake_target_changed",
                "The current claim holder changed during wake creation; resolve the "
                "target again and retry.",
            )
        if not created["deduplicated"]:
            recipient_snapshot = dict(recipients[0]["routing_snapshot"])
            recipient_snapshot["messageability"] = routing
            recipient_snapshot[EXPLICIT_WAKE_ROUTING_FLAG] = True
            marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
            conn.execute(
                "UPDATE session_message_recipients SET routing_snapshot="
                + marker
                + " WHERE message_id="
                + marker
                + " AND session_id="
                + marker,
                (
                    json.dumps(recipient_snapshot, sort_keys=True),
                    message_id,
                    recipient.session_id,
                ),
            )
        conn.commit()
        details = message_details(conn, message_id)
    except Exception:
        conn.rollback()
        raise
    return _wake_result(
        details,
        target_session_id=recipient.session_id,
        target_liveness=recipient.liveness,
        routing=routing,
        deduplicated=bool(created["deduplicated"]),
    )


__all__ = [
    "SESSION_WAKE_RESULT_WAIT_SECONDS",
    "request_session_wake",
    "wait_for_session_wake_result",
]
