"""One-shot operator wake requests over the durable message relay."""

from __future__ import annotations

import json
from datetime import datetime
from time import monotonic, sleep
from typing import Any

from yoke_contracts.session_control.models import RecipientSelector
from yoke_contracts.session_control.wake import MANUAL_WAKE_SELECTOR_FLAG
from yoke_contracts.session_control.wake_instruction import native_wake_instruction
from yoke_core.domain import db_backend
from yoke_core.domain.session_message_authorization import project_policy
from yoke_core.domain.session_message_routing import messageability
from yoke_core.domain.session_message_selectors import resolve_recipients
from yoke_core.domain.session_message_service import send_message
from yoke_core.domain.session_message_store import (
    begin_message_mutation,
    body_sha256,
    message_details,
)
from yoke_core.domain.session_message_types import (
    ResolvedRecipient,
    SessionMessageError,
    utc_now,
)
from yoke_core.domain.session_operator_authority import (
    require_operator_or_steering_authority,
)
from yoke_core.domain.session_relay_machine_versions import (
    connected_relay_routes,
    machine_surface_versions,
)


_PLACEHOLDER_PROMPT = "Manual session wake requested."
MANUAL_WAKE_RESULT_WAIT_SECONDS = 10.0
_RESULT_POLL_SECONDS = 0.25


def _selector(*, session_id: str | None, item_ref: str | None) -> RecipientSelector:
    return RecipientSelector(
        session_ids=[session_id] if session_id else [],
        item_refs=[item_ref] if item_ref else [],
    )


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
        {
            "executor_surface": recipient.executor_surface,
            "executor_version": recipient.executor_version,
        },
        liveness=recipient.liveness,
        machine_surface_versions=versions,
        force_stopped_route=True,
    )
    if recipient.liveness == "terminated":
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
) -> dict[str, Any]:
    wake_attempts = [
        attempt
        for attempt in details.get("attempts", [])
        if attempt.get("attempt_kind") in {"wake_relay", "wake_broker"}
    ]
    attempt = wake_attempts[-1] if wake_attempts else None
    message_id = str(details["message_id"])
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
    }


def wait_for_manual_wake_result(
    conn: Any,
    result: dict[str, Any],
    *,
    wait_seconds: float = MANUAL_WAKE_RESULT_WAIT_SECONDS,
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
            }
            if attempt.get("result_code"):
                return latest
        remaining = deadline - monotonic()
        if remaining <= 0:
            return latest
        conn.commit()
        sleep(min(_RESULT_POLL_SECONDS, remaining))


def request_manual_wake(
    conn: Any,
    *,
    actor_id: int,
    caller_session_id: str,
    session_id: str | None,
    item_ref: str | None,
    prompt: str | None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Queue one forced stopped-route wake and return body-free attempt facts."""
    current = now or utc_now()
    target_selector = _selector(session_id=session_id, item_ref=item_ref)
    begin_message_mutation(conn)
    try:
        recipient = _one_recipient(
            resolve_recipients(conn, target_selector, now=current)
        )
        require_operator_or_steering_authority(
            conn,
            actor_id=actor_id,
            caller_session_id=caller_session_id,
            project_id=recipient.project_id,
        )
        routing = _stopped_route(conn, recipient, now=current)
        created = send_message(
            conn,
            actor_id=actor_id,
            sender_session_id=caller_session_id,
            selector=target_selector,
            body=prompt or _PLACEHOLDER_PROMPT,
            now=current,
            commit=False,
        )
        message_id = str(created["message_id"])
        details = message_details(conn, message_id)
        if len(details.get("recipients", [])) != 1:
            raise SessionMessageError(
                "wake_target_changed",
                "The current claim holder changed during wake creation; resolve the "
                "target again and retry.",
            )
        final_prompt = prompt or native_wake_instruction(message_id)
        limit = project_policy(conn, recipient.project_id).max_body_bytes
        if len(final_prompt.encode("utf-8")) > limit:
            raise SessionMessageError(
                "body_too_large",
                f"wake prompt exceeds the project maximum of {limit} bytes",
                jsonpath="$.payload.prompt",
            )
        selector_snapshot = dict(details.get("selector_snapshot") or {})
        selector_snapshot[MANUAL_WAKE_SELECTOR_FLAG] = True
        recipient_snapshot = dict(details["recipients"][0]["routing_snapshot"])
        recipient_snapshot["messageability"] = routing
        marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
        conn.execute(
            "UPDATE session_messages SET body="
            + marker
            + ",body_sha256="
            + marker
            + ",selector_snapshot="
            + marker
            + " WHERE message_id="
            + marker,
            (
                final_prompt,
                body_sha256(final_prompt),
                json.dumps(selector_snapshot, sort_keys=True, separators=(",", ":")),
                message_id,
            ),
        )
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
    )


__all__ = [
    "MANUAL_WAKE_RESULT_WAIT_SECONDS",
    "request_manual_wake",
    "wait_for_manual_wake_result",
]
