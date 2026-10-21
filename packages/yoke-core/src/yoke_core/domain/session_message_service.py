"""Transactional product operations for fleet session messages."""

from __future__ import annotations

from yoke_contracts.timestamps import parse_instant

from datetime import datetime, timedelta
from typing import Any

from yoke_contracts.session_control.models import RecipientSelector
from yoke_contracts.session_control.sender_surface import (
    HARNESS_SESSION_SENDER_SURFACE,
)
from yoke_contracts.session_control.terminal_report import (
    terminal_report_idempotency_key,
)
from yoke_core.domain.db_savepoint import savepoint
from yoke_core.domain.actor_message_recipients import (
    actor_message_limits,
    resolve_actor_recipients,
)
from yoke_core.domain.session_message_authorization import (
    authorize_recipients,
    authorize_universe,
)
from yoke_core.domain.session_item_scope import SessionItemScope
from yoke_core.domain.session_message_liveness import applied_liveness
from yoke_core.domain.session_message_recipient_scope import owner_key, recipient_policy
from yoke_core.domain.session_message_selectors import (
    confirmation_token,
    resolve_recipients,
)
from yoke_core.domain.session_message_store import (
    begin_message_mutation,
    body_sha256,
    insert_message,
)
from yoke_core.domain.session_message_queries import get_message
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
    record_steering_row,
)
from yoke_core.domain.session_message_terminal import (
    reporting_episode_marker,
    resolve_terminal_report_item,
)
from yoke_core.domain.session_message_launch_queue import (
    pending_item_launch,
    launch_confirmation,
    launch_snapshot,
    launch_result,
)
from yoke_core.domain.session_message_zero_recipients import require_recipients
from yoke_core.hooks.relayed_session_identity import session_ownership_refusal
from yoke_core.domain.steering_recipient_projection import (
    previewed_steering_recipient,
    stored_steering_recipient,
)


def _public_recipients(recipients: list[ResolvedRecipient]) -> list[dict[str, Any]]:
    return [recipient.public() for recipient in recipients]


def _recipient_policies(conn, *, actor_id, recipients, additional_project_ids=()):
    policies = authorize_recipients(
        conn,
        actor_id=actor_id,
        recipients=recipients,
        additional_project_ids=additional_project_ids,
    )
    owned = {("project", pid): policy for pid, policy in policies.items()}
    for recipient in recipients:
        row = recipient.routing_snapshot()
        owned[owner_key(row)] = recipient_policy(conn, row)
    return owned


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
    reported_item: SessionItemScope | None = None,
) -> SteeringAddress | None:
    """Resolve where a role-addressed send belongs, before any seat is known."""
    if not selector.steering:
        return None
    return resolve_steering_address(
        conn,
        selector,
        sender_session_id=sender_session_id,
        reported_item=reported_item,
    )


def preview_message(
    conn: Any,
    *,
    actor_id: int,
    selector: RecipientSelector,
    sender_session_id: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = parse_instant(utc_now() if now is None else now)
    address = _steering_address(conn, selector, sender_session_id)
    recipients = resolve_recipients(
        conn,
        selector,
        now=now,
        actor_id=actor_id,
        steering_target=address.coverage_target() if address else None,
    )
    actor_recipients = resolve_actor_recipients(
        conn, selector, sender_actor_id=actor_id
    )
    launch = (
        pending_item_launch(conn, selector, recipients, now=now)
        if not address and not actor_recipients
        else None
    )
    if address is None and launch is None:
        require_recipients(recipients, selector, actor_recipients=actor_recipients)
    policies = _recipient_policies(
        conn,
        actor_id=actor_id,
        recipients=recipients,
        additional_project_ids=([address.project_id] if address else [])
        + ([launch["project_id"]] if launch else []),
    )
    if selector.universe:
        authorize_universe(conn, actor_id=actor_id, policies=policies.values())
    public = _public_recipients(recipients)
    public_actors = [recipient.public() for recipient in actor_recipients]
    steering = (
        previewed_steering_recipient(
            conn, address, seat_session_id=seat_session_id(conn, address)[0]
        )
        if address
        else None
    )
    return {
        "recipients": public,
        "actor_recipients": public_actors,
        "recipient_count": len(public)
        + len(public_actors)
        + bool(steering)
        + bool(launch),
        "applied_liveness": list(applied_liveness(selector)),
        "confirmation_token": launch_confirmation(
            confirmation_token(selector, recipients, actor_recipients=actor_recipients),
            launch,
        ),
        **launch_result(
            conn,
            {
                "selector_snapshot": launch_snapshot(
                    _selector_snapshot(selector), launch
                )
            },
            now=now,
        ),
        **({"steering_recipient": steering} if steering else {}),
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
    now = parse_instant(utc_now() if now is None else now)
    current = now
    if actor_id is not None and sender_session_id:
        refusal = session_ownership_refusal(conn, sender_session_id, actor_id)
        if refusal:
            raise SessionMessageError("sender_session_forbidden", refusal)
    begin_message_mutation(conn)
    # A caller-owned transaction (commit=False) keeps its earlier writes when
    # this send fails; only the send's own writes roll back.
    with savepoint(conn, "_yoke_send_message", owns=commit):
        reported_item = resolve_terminal_report_item(
            conn, sender_session_id=sender_session_id, body=body
        )
        address = _steering_address(conn, selector, sender_session_id, reported_item)
        recipients = resolve_recipients(
            conn,
            selector,
            now=current,
            actor_id=actor_id,
            steering_target=address.coverage_target() if address else None,
        )
        actor_recipients = resolve_actor_recipients(
            conn, selector, sender_actor_id=actor_id
        )
        launch = (
            pending_item_launch(conn, selector, recipients, now=current)
            if not address and not actor_recipients
            else None
        )
        if address is None and launch is None:
            require_recipients(recipients, selector, actor_recipients=actor_recipients)
        policies = _recipient_policies(
            conn,
            actor_id=actor_id,
            recipients=recipients,
            additional_project_ids=([address.project_id] if address else [])
            + ([launch["project_id"]] if launch else []),
        )
        actor_limits = actor_message_limits(conn, actor_recipients)
        expected_confirmation = launch_confirmation(
            confirmation_token(selector, recipients, actor_recipients=actor_recipients),
            launch,
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
        terminal_key = (
            terminal_report_idempotency_key(
                sender_session_id,
                reported_item.item_id,
                reported_item.claim_id,
                reporting_episode_marker(conn, sender_session_id),
            )
            if reported_item is not None and sender_session_id
            else None
        )
        expiry_hours = min(expiry_limits)
        expires_at = current + timedelta(hours=expiry_hours)
        wake_after_by_owner = {scope: current for scope in policies}
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
            selector_snapshot=launch_snapshot(_selector_snapshot(selector), launch),
            idempotency_key=terminal_key or idempotency_key,
            idempotency_intent_only=(
                terminal_key is not None or idempotency_intent_only
            ),
            created_at=current,
            expires_at=expires_at,
            recipients=recipients,
            actor_recipients=actor_recipients,
            wake_after_by_owner=wake_after_by_owner,
        )
        if address is not None and created:
            record_steering_row(conn, address, details, current)
        if commit:
            conn.commit()
        selected = (
            _public_recipients(recipients) if created else public_recipients(details)
        )
        selected_actors = (
            [recipient.public() for recipient in actor_recipients]
            if created
            else details.get("actor_recipients", [])
        )
        steering = stored_steering_recipient(conn, str(details["message_id"]))
        queued = launch_result(conn, details, now=current)
        result = {
            "message_id": details["message_id"],
            "recipients": selected,
            "actor_recipients": selected_actors,
            "recipient_count": (
                len(selected) + len(selected_actors) + bool(steering) + bool(queued)
            ),
            "deduplicated": not created,
            **queued,
        }
        if not created and details.get("body_sha256") != body_sha256(body):
            result["collapsed_differing_body"] = True
        if steering is not None:
            result["steering_recipient"] = steering
        return result


__all__ = ["get_message", "preview_message", "send_message"]
