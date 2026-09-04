"""Transactional product operations for fleet session messages."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from yoke_contracts.session_control.models import RecipientSelector
from yoke_contracts.session_control.sender_surface import (
    HARNESS_SESSION_SENDER_SURFACE,
)
from yoke_contracts.session_control.terminal_report import (
    is_terminal_done_report,
    terminal_report_idempotency_key,
)
from yoke_core.domain.actor_message_recipients import (
    ResolvedActorRecipient,
    actor_message_limits,
    resolve_actor_recipients,
)
from yoke_core.domain.session_message_authorization import (
    authorize_recipients,
    authorize_universe,
)
from yoke_core.domain.session_item_scope import session_item_scope
from yoke_core.domain.session_message_liveness import applied_liveness
from yoke_core.domain.session_message_selectors import (
    confirmation_token,
    resolve_recipients,
)
from yoke_core.domain.session_message_store import (
    begin_message_mutation,
    insert_message,
)
from yoke_core.domain.session_message_queries import get_message, list_messages
from yoke_core.domain.session_message_reads import public_recipients
from yoke_core.domain.session_message_substance import validate_body
from yoke_core.domain.session_message_types import (
    ResolvedRecipient,
    SessionMessageError,
    utc_now,
)
from yoke_core.domain.session_message_steering import (
    SteeringAddress,
    resolve_steering_address,
    seat_session_id,
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


def _steering_address(
    conn: Any,
    selector: RecipientSelector,
    sender_session_id: str | None,
) -> SteeringAddress | None:
    """Resolve where a role-addressed send belongs, before any seat is known."""
    if not selector.steering:
        return None
    return resolve_steering_address(conn, selector, sender_session_id=sender_session_id)


def _terminal_report_key(
    conn: Any,
    *,
    sender_session_id: str | None,
    body: str,
) -> str | None:
    """The dedupe key a terminal close-out report carries, if it is one.

    A derived key replaces whatever the caller offered because a retry after
    a refusal may reword the report. One key per (sender session, item,
    terminal state) is what makes the seat read it once.
    """
    if not sender_session_id or not is_terminal_done_report(body):
        return None
    scope = session_item_scope(conn, sender_session_id)
    if scope is None:
        return None
    return terminal_report_idempotency_key(sender_session_id, scope.item_id)


def preview_message(
    conn: Any,
    *,
    actor_id: int,
    selector: RecipientSelector,
    sender_session_id: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    address = _steering_address(conn, selector, sender_session_id)
    recipients = resolve_recipients(
        conn,
        selector,
        now=now,
        steering_target=address.coverage_target() if address else None,
    )
    actor_recipients = resolve_actor_recipients(
        conn, selector, sender_actor_id=actor_id
    )
    if address is None:
        require_recipients(recipients, selector, actor_recipients=actor_recipients)
    policies = authorize_recipients(
        conn,
        actor_id=actor_id,
        recipients=recipients,
        additional_project_ids=(address.project_id,) if address else (),
    )
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
        **(
            {"steering_scope": dict(address.scope), "parked": not recipients}
            if address
            else {}
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
    idempotency_intent_only: bool = False,
    supplied_confirmation_token: str | None = None,
    now: datetime | None = None,
    commit: bool = True,
) -> dict[str, Any]:
    current = now or utc_now()
    begin_message_mutation(conn)
    try:
        address = _steering_address(conn, selector, sender_session_id)
        recipients = resolve_recipients(
            conn,
            selector,
            now=current,
            steering_target=address.coverage_target() if address else None,
        )
        actor_recipients = resolve_actor_recipients(
            conn, selector, sender_actor_id=actor_id
        )
        if address is None:
            require_recipients(recipients, selector, actor_recipients=actor_recipients)
        policies = authorize_recipients(
            conn,
            actor_id=actor_id,
            recipients=recipients,
            additional_project_ids=(address.project_id,) if address else (),
        )
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
        terminal_key = _terminal_report_key(
            conn, sender_session_id=sender_session_id, body=body
        )
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
            idempotency_key=terminal_key or idempotency_key,
            idempotency_intent_only=(
                terminal_key is not None or idempotency_intent_only
            ),
            created_at=current,
            expires_at=expires_at,
            recipients=recipients,
            actor_recipients=actor_recipients,
            wake_after_by_project=wake_after_by_project,
        )
        if address is not None and created:
            _record_steering_row(conn, address, details, current)
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


def _record_steering_row(
    conn: Any,
    address: SteeringAddress,
    details: dict[str, Any],
    created_at: datetime,
) -> None:
    """Record the durable role-addressed row beside any live seat delivery."""
    from yoke_core.domain.steering_message_recipients import (
        record_steering_recipient,
    )

    seat_id, seat = seat_session_id(conn, address)
    record_steering_recipient(
        conn,
        message_id=str(details["message_id"]),
        scope=address.scope,
        project_id=address.project_id,
        sender_item_id=address.sender_item_id,
        seat_session_id=seat_id,
        seat_claim_id=int(seat["claim_id"]) if seat else None,
        created_at=created_at,
    )


__all__ = ["get_message", "list_messages", "preview_message", "send_message"]
