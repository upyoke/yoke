"""Bounded rendering for authenticated Fleet message hook context."""

from __future__ import annotations

import json
import shlex

from yoke_contracts.session_control.teaching import (
    FLEET_INVALID_MESSAGE_ID_GUIDANCE,
    canonical_fleet_message_id,
)
from yoke_core.hooks.session_message_delivery_port import (
    LeasedSessionMessage,
    SessionMessageLease,
)


def _render_message(
    message: LeasedSessionMessage,
    *,
    token: str,
    acknowledgement: str,
) -> str:
    message_id = canonical_fleet_message_id(message.message_id) or "invalid-message-id"
    body_lines = [
        "| "
        + json.dumps(line, ensure_ascii=False)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u0085", "\\u0085")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
        for line in message.body.split("\n")
    ]
    sender = message.sender_actor_label or f"actor {message.sender_actor_id}"
    if message.sender_session_id:
        sender_description = f"{sender} via session {message.sender_session_id}"
    else:
        actor_kind = message.sender_actor_kind or "actor"
        surface = (
            message.sender_surface_label or message.sender_surface or "unknown surface"
        )
        sender_description = f"{sender} ({actor_kind}, {surface})"
    return "\n".join(
        (
            f"=== BEGIN YOKE SESSION MESSAGE DELIVERY {token} {message_id} ===",
            f"Authenticated sender: {sender_description}",
            *body_lines,
            acknowledgement,
            "=== END YOKE SESSION MESSAGE DELIVERY ===",
        )
    )


def _parent_overflow_notice(hidden_count: int, session_id: str) -> str:
    # Quoted, never shortened: a clipped session id produces a listing
    # command that quietly reads the wrong backlog, or none at all.
    recipient = shlex.quote(session_id or "CURRENT-SESSION-ID")
    return " ".join(
        (
            f"{hidden_count} additional unacknowledged session message(s) were "
            "not expanded because hook context is bounded.",
            "List the backlog with "
            f"`yoke messages list --recipient-session {recipient} "
            "--state unacknowledged`.",
            "Read a full body with `yoke messages get MESSAGE-ID`.",
        )
    )


def _parent_blocks(
    lease: SessionMessageLease,
    *,
    session_id: str,
    token: str,
) -> list[str]:
    """Expand leased messages before the composer admits bodies or stubs."""
    blocks = []
    for message in lease.messages:
        message_id = canonical_fleet_message_id(message.message_id)
        acknowledgement = (
            f"Acknowledge: `yoke messages acknowledge {message_id}`"
            if message_id
            else FLEET_INVALID_MESSAGE_ID_GUIDANCE
        )
        blocks.append(
            _render_message(message, token=token, acknowledgement=acknowledgement)
        )
    hidden_count = max(0, lease.remaining_count)
    if hidden_count:
        blocks.append(_parent_overflow_notice(hidden_count, session_id))
    return blocks


def render_lease(
    lease: SessionMessageLease,
    *,
    session_id: str,
) -> tuple[str, str]:
    """Return the whole lease as model context, plus its settlement token.

    Bounding happens where delivery is actually decided: the harness
    context composer admits whole messages that fit, substitutes a stub for
    an oversized body, and leaves the rest pending for the next hook.
    Trimming it here instead would make those outcomes look identical to
    settlement.
    """
    token = f"YOKE_SESSION_MESSAGE_LEASE:{lease.lease_id}"
    rendered = "\n\n".join(_parent_blocks(lease, session_id=session_id, token=token))
    return rendered, token


__all__ = ["render_lease"]
