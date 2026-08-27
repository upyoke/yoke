"""Transactional product operations for fleet session messages."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from yoke_contracts.session_control.models import RecipientSelector
from yoke_core.domain.session_message_authorization import (
    authorize_recipients,
    authorize_universe,
    can_read_project,
)
from yoke_core.domain.session_message_liveness import applied_liveness
from yoke_core.domain.session_message_selectors import (
    confirmation_token,
    resolve_recipients,
)
from yoke_core.domain.session_message_store import (
    acknowledge_recipient,
    begin_message_mutation,
    cancel_message_rows,
    insert_message,
    list_message_ids,
    message_details,
    public_recipients,
    recipient_project_ids,
)
from yoke_core.domain.session_message_types import (
    ResolvedRecipient,
    SessionMessageError,
    utc_now,
)


def _require_recipients(recipients: list[ResolvedRecipient]) -> None:
    if not recipients:
        raise SessionMessageError(
            "zero_recipients", "recipient selector resolved to zero sessions"
        )


def _public_recipients(recipients: list[ResolvedRecipient]) -> list[dict[str, Any]]:
    return [recipient.public() for recipient in recipients]


def _selector_snapshot(selector: RecipientSelector) -> dict[str, Any]:
    """Record the selector plus the liveness it actually resolved against."""
    return {
        **selector.model_dump(mode="json"),
        "applied_liveness": list(applied_liveness(selector)),
    }


def preview_message(
    conn: Any,
    *,
    actor_id: int,
    selector: RecipientSelector,
    now: datetime | None = None,
) -> dict[str, Any]:
    recipients = resolve_recipients(conn, selector, now=now)
    _require_recipients(recipients)
    policies = authorize_recipients(conn, actor_id=actor_id, recipients=recipients)
    if selector.universe:
        authorize_universe(conn, actor_id=actor_id, policies=policies.values())
    public = _public_recipients(recipients)
    return {
        "recipients": public,
        "recipient_count": len(public),
        "applied_liveness": list(applied_liveness(selector)),
        "confirmation_token": confirmation_token(selector, recipients),
    }


def _validate_routes(recipients: list[ResolvedRecipient]) -> None:
    unsupported = [
        r.session_id for r in recipients if not r.messageability.get("messageable")
    ]
    if unsupported:
        raise SessionMessageError(
            "unsupported_route",
            f"recipient sessions have no version-qualified hook route: {unsupported}",
        )


def send_message(
    conn: Any,
    *,
    actor_id: int,
    sender_session_id: str | None,
    selector: RecipientSelector,
    body: str,
    idempotency_key: str | None = None,
    supplied_confirmation_token: str | None = None,
    now: datetime | None = None,
    commit: bool = True,
) -> dict[str, Any]:
    """Resolve, authorize, snapshot, and optionally commit one message."""
    current = now or utc_now()
    begin_message_mutation(conn)
    try:
        recipients = resolve_recipients(conn, selector, now=current)
        _require_recipients(recipients)
        policies = authorize_recipients(conn, actor_id=actor_id, recipients=recipients)
        expected_confirmation = confirmation_token(selector, recipients)
        if selector.universe:
            authorize_universe(conn, actor_id=actor_id, policies=policies.values())
            required = any(
                policy.broadcast_requires_confirmation for policy in policies.values()
            )
            if supplied_confirmation_token != expected_confirmation and (
                required or supplied_confirmation_token is not None
            ):
                raise SessionMessageError(
                    "broadcast_confirmation_required",
                    "universe broadcast requires the exact current preview token",
                    jsonpath="$.payload.confirmation_token",
                )
        elif (
            supplied_confirmation_token is not None
            and supplied_confirmation_token != expected_confirmation
        ):
            raise SessionMessageError(
                "recipient_snapshot_changed",
                "resolved recipient snapshot changed after preview",
                jsonpath="$.payload.confirmation_token",
            )
        _validate_routes(recipients)
        body_bytes = len(body.encode("utf-8"))
        if body_bytes == 0:
            raise SessionMessageError("body_empty", "message body must not be empty")
        max_body_bytes = min(policy.max_body_bytes for policy in policies.values())
        if body_bytes > max_body_bytes:
            raise SessionMessageError(
                "body_too_large",
                f"message body is {body_bytes} bytes; maximum is {max_body_bytes}",
                jsonpath="$.payload.body",
            )
        expires_at = current + timedelta(
            hours=min(policy.expiry_hours for policy in policies.values())
        )
        wake_after_by_project = {pid: current for pid in policies}
        details, created = insert_message(
            conn,
            sender_actor_id=actor_id,
            sender_session_id=sender_session_id,
            body=body,
            selector_snapshot=_selector_snapshot(selector),
            idempotency_key=idempotency_key,
            created_at=current,
            expires_at=expires_at,
            recipients=recipients,
            wake_after_by_project=wake_after_by_project,
        )
        if commit:
            conn.commit()
        selected = (
            _public_recipients(recipients) if created else public_recipients(details)
        )
        return {
            "message_id": details["message_id"],
            "recipients": selected,
            "recipient_count": len(selected),
            "deduplicated": not created,
        }
    except Exception:
        conn.rollback()
        raise


def _visible(
    conn: Any,
    details: dict[str, Any],
    *,
    actor_id: int,
    session_id: str | None,
) -> bool:
    if int(details["sender_actor_id"]) == actor_id:
        return True
    if session_id and any(
        str(row["session_id"]) == session_id for row in details["recipients"]
    ):
        return True
    project_ids = recipient_project_ids(details)
    return bool(project_ids) and all(
        can_read_project(conn, actor_id=actor_id, project_id=project_id)
        for project_id in project_ids
    )


def get_message(
    conn: Any,
    *,
    message_id: str,
    actor_id: int,
    session_id: str | None,
) -> dict[str, Any]:
    from yoke_core.domain.session_message_delivery import expire_due_recipients

    expire_due_recipients(conn)
    details = message_details(conn, message_id)
    if not _visible(conn, details, actor_id=actor_id, session_id=session_id):
        raise SessionMessageError(
            "message_forbidden", "message is not visible to the calling actor"
        )
    return details


def list_messages(
    conn: Any,
    *,
    actor_id: int,
    caller_session_id: str | None,
    state: str | None = None,
    session_id: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    from yoke_core.domain.session_message_delivery import expire_due_recipients

    expire_due_recipients(conn)
    ids = list_message_ids(
        conn,
        state=state,
        session_id=session_id,
        limit=min(500, max(limit * 4, limit)),
    )
    visible: list[dict[str, Any]] = []
    for message_id in ids:
        details = message_details(conn, message_id)
        if _visible(
            conn,
            details,
            actor_id=actor_id,
            session_id=caller_session_id,
        ):
            visible.append(details)
        if len(visible) >= limit:
            break
    return visible


def acknowledge_message(
    conn: Any,
    *,
    message_id: str,
    session_id: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    from yoke_core.domain.session_message_delivery import expire_due_recipients

    expire_due_recipients(conn, now=now)
    details = acknowledge_recipient(
        conn,
        message_id=message_id,
        session_id=session_id,
        acknowledged_at=now or utc_now(),
    )
    recipient = next(
        (
            row
            for row in details.get("recipients", [])
            if str(row.get("session_id") or "") == session_id
        ),
        None,
    )
    if recipient is not None:
        from yoke_core.domain.session_private_route_qualification import (
            PrivateRouteQualificationError,
            consume_qualification_grant,
            qualification_for_message,
        )

        try:
            grant = qualification_for_message(
                conn,
                {"message_id": message_id, **recipient},
                operation="message_active",
                route="hook",
                now=now,
            )
            if grant is not None:
                consume_qualification_grant(conn, grant)
        except PrivateRouteQualificationError:
            # Qualification is acceptance evidence, never product ack authority.
            # A raced, expired, or revoked grant stays unproven without making
            # an otherwise valid delivered message impossible to acknowledge.
            pass
    conn.commit()
    return details


def cancel_message(
    conn: Any,
    *,
    message_id: str,
    actor_id: int,
    reason: str = "cancelled_by_sender",
    now: datetime | None = None,
) -> dict[str, Any]:
    details = message_details(conn, message_id)
    sender = int(details["sender_actor_id"]) == actor_id
    project_ids = {
        int(recipient["project_id"])
        for recipient in details.get("recipients", [])
        if recipient.get("project_id") is not None
    }
    if not sender:
        from yoke_core.domain.actor_permissions import (
            PERM_PROJECT_ADMIN,
            permission_decision,
        )

        administers_all = bool(project_ids) and all(
            permission_decision(
                conn,
                actor_id=actor_id,
                project_id=project_id,
                permission_key=PERM_PROJECT_ADMIN,
            ).allowed
            for project_id in project_ids
        )
    else:
        administers_all = False
    if not sender and not administers_all:
        raise SessionMessageError(
            "cancel_forbidden",
            "only the sender or an administrator of every target project may cancel",
        )
    if administers_all and reason == "cancelled_by_sender":
        reason = "cancelled_by_project_admin"
    cancelled = cancel_message_rows(
        conn,
        message_id=message_id,
        actor_id=actor_id,
        reason=reason,
        cancelled_at=now or utc_now(),
    )
    conn.commit()
    return cancelled


__all__ = [
    "acknowledge_message",
    "cancel_message",
    "get_message",
    "list_messages",
    "preview_message",
    "send_message",
]
