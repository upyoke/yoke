"""Transactional product operations for fleet session messages."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from yoke_contracts.session_control.models import RecipientSelector
from yoke_contracts.session_control.sender_surface import (
    HARNESS_SESSION_SENDER_SURFACE,
)
from yoke_core.domain.actor_message_recipients import (
    ResolvedActorRecipient,
    acknowledge_actor_recipient,
    actor_message_limits,
    resolve_actor_recipients,
)
from yoke_core.domain.session_message_authorization import (
    authorize_recipients,
    authorize_universe,
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
)
from yoke_core.domain.session_message_queries import get_message, list_messages
from yoke_core.domain.session_message_reads import message_details, public_recipients
from yoke_core.domain.session_message_substance import validate_body
from yoke_core.domain.session_message_types import (
    ResolvedRecipient,
    SessionMessageError,
    utc_now,
)
from yoke_core.domain.session_message_zero_recipients import require_recipients


def _public_recipients(recipients: list[ResolvedRecipient]) -> list[dict[str, Any]]:
    return [recipient.public() for recipient in recipients]


def _public_actor_recipients(
    recipients: list[ResolvedActorRecipient],
) -> list[dict[str, Any]]:
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
    actor_recipients = resolve_actor_recipients(
        conn, selector, sender_actor_id=actor_id
    )
    require_recipients(recipients, selector, actor_recipients=actor_recipients)
    policies = authorize_recipients(conn, actor_id=actor_id, recipients=recipients)
    if selector.universe:
        authorize_universe(conn, actor_id=actor_id, policies=policies.values())
    public = _public_recipients(recipients)
    public_actors = _public_actor_recipients(actor_recipients)
    return {
        "recipients": public,
        "actor_recipients": public_actors,
        "recipient_count": len(public) + len(public_actors),
        "applied_liveness": list(applied_liveness(selector)),
        "confirmation_token": confirmation_token(
            selector, recipients, actor_recipients=actor_recipients
        ),
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
    message_id: str | None = None,
    actor_id: int,
    sender_session_id: str | None,
    sender_surface: str | None = None,
    selector: RecipientSelector,
    body: str,
    idempotency_key: str | None = None,
    supplied_confirmation_token: str | None = None,
    now: datetime | None = None,
    commit: bool = True,
) -> dict[str, Any]:
    current = now or utc_now()
    begin_message_mutation(conn)
    try:
        recipients = resolve_recipients(conn, selector, now=current)
        actor_recipients = resolve_actor_recipients(
            conn, selector, sender_actor_id=actor_id
        )
        require_recipients(recipients, selector, actor_recipients=actor_recipients)
        policies = authorize_recipients(conn, actor_id=actor_id, recipients=recipients)
        actor_limits = actor_message_limits(conn, actor_recipients)
        expected_confirmation = confirmation_token(
            selector, recipients, actor_recipients=actor_recipients
        )
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
        body_limits = [policy.max_body_bytes for policy in policies.values()]
        expiry_limits = [policy.expiry_hours for policy in policies.values()]
        if actor_limits is not None:
            body_limits.append(actor_limits.max_body_bytes)
            expiry_limits.append(actor_limits.expiry_hours)
        validate_body(body, max_body_bytes=min(body_limits))
        expiry_hours = min(expiry_limits)
        expires_at = current + timedelta(hours=expiry_hours)
        wake_after_by_project = {pid: current for pid in policies}
        details, created = insert_message(
            conn,
            message_id=message_id,
            sender_actor_id=actor_id,
            sender_session_id=sender_session_id,
            sender_surface=(
                sender_surface
                or (HARNESS_SESSION_SENDER_SURFACE if sender_session_id else None)
            ),
            body=body,
            selector_snapshot=_selector_snapshot(selector),
            idempotency_key=idempotency_key,
            created_at=current,
            expires_at=expires_at,
            recipients=recipients,
            actor_recipients=actor_recipients,
            wake_after_by_project=wake_after_by_project,
        )
        if commit:
            conn.commit()
        selected = (
            _public_recipients(recipients) if created else public_recipients(details)
        )
        selected_actors = (
            _public_actor_recipients(actor_recipients)
            if created
            else details.get("actor_recipients", [])
        )
        return {
            "message_id": details["message_id"],
            "recipients": selected,
            "actor_recipients": selected_actors,
            "recipient_count": len(selected) + len(selected_actors),
            "deduplicated": not created,
        }
    except Exception:
        conn.rollback()
        raise


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


def acknowledge_actor_message(
    conn: Any,
    *,
    message_id: str,
    actor_id: int,
    now: datetime | None = None,
) -> dict[str, Any]:
    acknowledge_actor_recipient(
        conn, message_id=message_id, actor_id=actor_id, read_at=now
    )
    conn.commit()
    return message_details(conn, message_id)


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
    "acknowledge_actor_message",
    "acknowledge_message",
    "cancel_message",
    "get_message",
    "list_messages",
    "preview_message",
    "send_message",
]
